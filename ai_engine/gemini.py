import base64
import io
import logging
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from PIL import Image

from ai_engine.personalization import build_system_prompt
from config import GEMINI_API_KEY, GEMINI_MODEL_NAME

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_PATH = Path(__file__).with_name("prompt.md")
_gemini_configured = False
_UNSUPPORTED_LOCATION_ERROR_FRAGMENT = "user location is not supported"


def _ensure_gemini_configured() -> None:
    global _gemini_configured

    if _gemini_configured:
        return

    if not GEMINI_API_KEY or GEMINI_API_KEY == "ВАШ_API_КЛЮЧ":
        raise ValueError(
            "GEMINI_API_KEY не установлен или имеет значение по умолчанию. Проверьте config.py."
        )

    genai.configure(api_key=GEMINI_API_KEY)
    _gemini_configured = True
    logger.info("Модуль Gemini успешно настроен.")


def _load_system_prompt() -> Optional[str]:
    try:
        logger.debug("Попытка загрузить системный промпт из: %s", _SYSTEM_PROMPT_PATH)
        if not _SYSTEM_PROMPT_PATH.exists():
            logger.error(
                "Файл системного промпта '%s' не найден. Модель будет инициализирована без него.",
                _SYSTEM_PROMPT_PATH,
            )
            return None

        prompt_content = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if prompt_content:
            logger.info(
                "Системный промпт успешно загружен из файла '%s'.",
                _SYSTEM_PROMPT_PATH,
            )
            return prompt_content

        logger.error("Файл системного промпта '%s' пуст.", _SYSTEM_PROMPT_PATH)
    except Exception as exc:
        logger.error("Ошибка при чтении файла системного промпта: %s", exc, exc_info=True)

    return None


def _prepare_history(history_from_main: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prepared_history: List[Dict[str, Any]] = []
    for message in history_from_main or []:
        if not isinstance(message, dict):
            continue

        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "model"}:
            continue

        prepared_parts = _prepare_history_parts(message.get("parts", []))
        if not prepared_parts:
            continue

        prepared_history.append({"role": role, "parts": prepared_parts})

    return prepared_history


def _prepare_history_parts(parts: Any) -> List[Dict[str, str]]:
    prepared_parts: List[Dict[str, str]] = []
    if not isinstance(parts, list):
        return prepared_parts

    for part in parts:
        if isinstance(part, dict) and part.get("text") is not None:
            text = str(part.get("text") or "").strip()
            if text:
                prepared_parts.append({"text": text})

    return prepared_parts


def _prepare_new_message(user_message_data: Dict[str, Any]) -> List[Union[str, Image.Image]]:
    content_parts: List[Union[str, Image.Image]] = []

    text = user_message_data.get("message", "")
    if text:
        content_parts.append(text)

    for file_info in user_message_data.get("files", []):
        try:
            model_part = file_info.get("model_part")
            if not model_part:
                logger.warning(
                    "Файл '%s' не содержит 'model_part'. Пропускаем.",
                    file_info.get("original_name"),
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
                        "Изображение '%s' добавлено в запрос.",
                        file_info.get("original_name"),
                    )
                else:
                    logger.warning(
                        "Некорректные данные изображения для файла '%s'.",
                        file_info.get("original_name"),
                    )
            elif "text" in model_part:
                content_parts.append(model_part["text"])
                logger.info(
                    "Текстовое содержимое файла '%s' добавлено в запрос.",
                    file_info.get("original_name"),
                )
        except Exception as exc:
            logger.error(
                "Критическая ошибка при обработке файла '%s': %s",
                file_info.get("original_name"),
                exc,
                exc_info=True,
            )
            content_parts.append(
                "\nОшибка обработки файла"
                f"Не удалось обработать файл '{file_info.get('original_name')}'."
            )

    return content_parts


def _google_api_error_message(exc: google_exceptions.GoogleAPICallError) -> str:
    return str(getattr(exc, "message", None) or exc)


def _is_unsupported_location_error(exc: google_exceptions.GoogleAPICallError) -> bool:
    error_message = _google_api_error_message(exc).lower()
    return (
        isinstance(exc, google_exceptions.FailedPrecondition)
        and _UNSUPPORTED_LOCATION_ERROR_FRAGMENT in error_message
    )


def _format_google_api_error(exc: google_exceptions.GoogleAPICallError) -> str:
    if _is_unsupported_location_error(exc):
        return (
            "Сервис недоступен"
            "Языковая модель сейчас недоступна из текущего региона. "
            "Обратитесь к администратору или попробуйте позже."
        )

    return (
        "Ошибка API"
        f"Произошла ошибка при обращении к API Google: {_google_api_error_message(exc)}"
    )


def gemini_stream(user_id: str, user_message_data: Dict[str, Any]) -> Generator[str, None, None]:
    try:
        _ensure_gemini_configured()

        try:
            system_prompt = build_system_prompt(user_id, user_message_data)
        except Exception as exc:
            logger.exception("Failed to build system prompt for user %s: %s", user_id, exc)
            system_prompt = _load_system_prompt()

        model_kwargs = {"model_name": GEMINI_MODEL_NAME}
        if system_prompt:
            model_kwargs["system_instruction"] = system_prompt

        model = genai.GenerativeModel(**model_kwargs)
        history = _prepare_history(user_message_data.get("history", []))
        chat_session = model.start_chat(history=history)
        logger.info(
            "Gemini: Сессия чата для '%s' создана с %s сообщениями в истории.",
            user_id,
            len(history),
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
                        "Gemini: Получен пустой chunk для '%s'. Вероятно, сработал фильтр безопасности.",
                        user_id,
                    )
                    continue

                if chunk.text:
                    yield chunk.text
                    any_text_generated = True

        except google_exceptions.GoogleAPICallError as exc:
            logger.error("Ошибка вызова API для '%s': %s", user_id, exc, exc_info=True)
            yield _format_google_api_error(exc)
            return
        except Exception as exc:
            logger.error(
                "Неожиданная ошибка при отправке сообщения для '%s': %s",
                user_id,
                exc,
                exc_info=True,
            )
            yield (
                "Внутренняя ошибка"
                "Произошла внутренняя ошибка при отправке вашего сообщения модели."
            )
            return

        if not any_text_generated:
            logger.warning("Поток для '%s' завершился без генерации текста.", user_id)
            try:
                if response_stream and response_stream.prompt_feedback:
                    block_reason = response_stream.prompt_feedback.block_reason
                    logger.error(
                        "Ответ для '%s' был заблокирован. Причина: %s.",
                        user_id,
                        block_reason,
                    )
                    yield (
                        "Запрос заблокирован"
                        "Модель не сгенерировала ответ. Ваш запрос или контекст диалога мог быть "
                        "заблокирован по соображениям безопасности. Попробуйте переформулировать его."
                    )
                else:
                    logger.error("Ответ для '%s' пуст, причина блокировки не найдена.", user_id)
                    yield (
                        "Пустой ответ"
                        "Модель не сгенерировала ответ. Это могло произойти из-за внутренних правил "
                        "безопасности или временной ошибки. Пожалуйста, попробуйте еще раз."
                    )
            except Exception as feedback_error:
                logger.error(
                    "Ошибка при получении prompt_feedback для '%s': %s",
                    user_id,
                    feedback_error,
                    exc_info=True,
                )
                yield (
                    "Пустой ответлан "
                    "Модель вернула пустой ответ, и не удалось определить причину. "
                    "Попробуйте переформулировать запрос."
                )

    except Exception as exc:
        logger.critical(
            "КРИТИЧЕСКАЯ неперехваченная ошибка в gemini_stream для '%s': %s",
            user_id,
            exc,
            exc_info=True,
        )
        error_text = str(exc)
        if "API key not valid" in error_text:
            yield (
                "Недействительный API-ключ"
                "Произошла критическая ошибка: API-ключ недействителен. Обратитесь к администратору."
            )
        else:
            yield (
                "Критическая ошибка"
                "Произошла критическая системная ошибка при обращении к языковой модели. "
                "Пожалуйста, попробуйте позже."
            )
