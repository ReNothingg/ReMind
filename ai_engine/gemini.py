import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from PIL import Image
import logging
import base64
import io
from typing import Any, Dict, Generator, List, Optional, Union
import os
from config import GEMINI_API_KEY, GEMINI_MODEL_NAME
from ai_engine.personalization import build_system_prompt
logger = logging.getLogger(__name__)
try:
    if not GEMINI_API_KEY or GEMINI_API_KEY == "ВАШ_API_КЛЮЧ":
        raise ValueError(
            "GEMINI_API_KEY не установлен или имеет значение по умолчанию. Проверьте файл config.py."
        )
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Модуль Gemini успешно настроен.")
except (ValueError, Exception) as e:
    logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось настроить API. Ошибка: {e}")


def _load_system_prompt() -> Optional[str]:

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_file_path = os.path.join(script_dir, "prompt.md")

        logger.debug(f"Попытка загрузить системный промпт из: {prompt_file_path}")

        if os.path.exists(prompt_file_path):
            with open(prompt_file_path, "r", encoding="utf-8") as f:
                prompt_content = f.read().strip()
                if prompt_content:
                    logger.info(
                        f"Системный промпт успешно загружен из файла '{prompt_file_path}'."
                    )
                    return prompt_content
                else:
                    logger.error(f"Файл системного промпта '{prompt_file_path}' пуст.")
        else:
            logger.error(
                f"Файл системного промпта '{prompt_file_path}' не найден. Модель будет инициализирована без него."
            )
    except Exception as e:
        logger.error(f"Ошибка при чтении файла системного промпта: {e}", exc_info=True)

    return None


def _prepare_history(history_from_main: List[Dict[str, Any]]) -> List[Dict[str, Any]]:

    return history_from_main or []


def _prepare_new_message(
    user_message_data: Dict[str, Any],
) -> List[Union[str, Image.Image]]:

    content_parts: List[Union[str, Image.Image]] = []

    text = user_message_data.get("message", "")
    if text:
        content_parts.append(text)

    for file_info in user_message_data.get("files", []):
        try:
            model_part = file_info.get("model_part")
            if not model_part:
                logger.warning(
                    f"Файл '{file_info.get('original_name')}' не содержит 'model_part'. Пропускаем."
                )
                continue
            if "inline_data" in model_part:
                mime_type = model_part["inline_data"].get("mime_type")
                base64_data = model_part["inline_data"].get("data")
                if mime_type and mime_type.startswith("image/") and base64_data:
                    image_bytes = base64.b64decode(base64_data)
                    image = Image.open(io.BytesIO(image_bytes))
                    content_parts.append(image)
                    logger.info(
                        f"Изображение '{file_info.get('original_name')}' добавлено в запрос."
                    )
                else:
                    logger.warning(
                        f"Некорректные данные изображения для файла '{file_info.get('original_name')}'."
                    )
            elif "text" in model_part:
                content_parts.append(model_part["text"])
                logger.info(
                    f"Текстовое содержимое файла '{file_info.get('original_name')}' добавлено в запрос."
                )

        except Exception as e:
            logger.error(
                f"Критическая ошибка при обработке файла '{file_info.get('original_name')}': {e}",
                exc_info=True,
            )
            content_parts.append(
                f"\n<error>Ошибка обработки файла</error>"
                f"Не удалось обработать файл '{file_info.get('original_name')}'."
            )

    return content_parts


def gemini_stream(
    user_id: str, user_message_data: Dict[str, Any]
) -> Generator[str, None, None]:
    try:
        try:
            system_prompt = build_system_prompt(user_id, user_message_data)
        except Exception as e:
            logger.exception(f"Failed to build system prompt for user {user_id}: {e}")
            system_prompt = _load_system_prompt()
        model_kwargs = {"model_name": GEMINI_MODEL_NAME}
        if system_prompt:
            model_kwargs["system_instruction"] = system_prompt

        model = genai.GenerativeModel(**model_kwargs)
        history = _prepare_history(user_message_data.get("history", []))
        chat_session = model.start_chat(history=history)
        logger.info(
            f"Gemini: Сессия чата для '{user_id}' создана с {len(history)} сообщениями в истории."
        )
        new_message_parts = _prepare_new_message(user_message_data)
        if not new_message_parts:
            yield "Пожалуйста, введите сообщение или прикрепите файл для начала диалога."
            return

        response_stream = None
        any_text_generated = False
        try:
            response_stream = chat_session.send_message(new_message_parts, stream=True)
            for chunk in response_stream:
                if not chunk.parts:
                    logger.warning(
                        f"Gemini: Получен пустой 'chunk' для '{user_id}'. Вероятно, сработал фильтр безопасности."
                    )
                    continue
                if chunk.text:
                    yield chunk.text
                    any_text_generated = True

        except google_exceptions.GoogleAPICallError as e:
            logger.error(f"Ошибка вызова API для '{user_id}': {e}", exc_info=True)
            yield f"<error>Ошибка API</error>Произошла ошибка при обращении к API Google: {e.message}"
            return
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при отправке сообщения для '{user_id}': {e}",
                exc_info=True,
            )
            yield "<error>Внутренняя ошибка</error>Произошла внутренняя ошибка при отправке вашего сообщения модели."
            return
        if not any_text_generated:
            logger.warning(f"Поток для '{user_id}' завершился без генерации текста.")
            try:
                if response_stream and response_stream.prompt_feedback:
                    block_reason = response_stream.prompt_feedback.block_reason
                    logger.error(
                        f"Ответ для '{user_id}' был заблокирован. Причина: {block_reason}."
                    )
                    yield (
                        "<error>Запрос заблокирован</error>"
                        "Модель не сгенерировала ответ. Ваш запрос или контекст диалога мог быть заблокирован "
                        "по соображениям безопасности. Попробуйте переформулировать его."
                    )
                else:
                    logger.error(
                        "Ответ для '{user_id}' пуст, причина блокировки не найдена."
                    )
                    yield (
                        "<error>Пустой ответ</error>"
                        "Модель не сгенерировала ответ. Это могло произойти из-за внутренних правил "
                        "безопасности или временной ошибки. Пожалуйста, попробуйте еще раз."
                    )
            except Exception as feedback_error:
                logger.error(
                    f"Ошибка при получении prompt_feedback для '{user_id}': {feedback_error}",
                    exc_info=True,
                )
                yield (
                    "<error>Пустой ответ</error>"
                    "Модель вернула пустой ответ, и не удалось определить причину. "
                    "Попробуйте переформулировать запрос."
                )

    except Exception as e:
        logger.critical(
            f"КРИТИЧЕСКАЯ неперехваченная ошибка в `gemini_stream` для '{user_id}': {e}",
            exc_info=True,
        )
        error_text = str(e)
        if "API key not valid" in error_text:
            yield (
                "<error>Недействительный API-ключ</error>"
                "Произошла критическая ошибка: API-ключ недействителен. Обратитесь к администратору."
            )
        else:
            yield (
                "<error>Критическая ошибка</error>"
                "Произошла критическая системная ошибка при обращении к языковой модели. "
                "Пожалуйста, попробуйте позже."
            )
