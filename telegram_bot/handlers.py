from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from aiogram.utils.chat_action import ChatActionSender

from services.telegram_chat_history import TelegramSessionSummary
from telegram_bot.callbacks import BotActionCallback, SessionSwitchCallback
from telegram_bot.keyboards import history_keyboard, primary_actions_keyboard
from telegram_bot.service import TelegramChatService

logger = logging.getLogger(__name__)

router = Router(name="remind_telegram")
router.callback_query.middleware(CallbackAnswerMiddleware())

STREAM_EDIT_INTERVAL_SECONDS = 1.2
STREAM_PREVIEW_LIMIT = 3500
TELEGRAM_MESSAGE_LIMIT = 4096


@router.message(CommandStart())
async def command_start(message: Message, chat_service: TelegramChatService) -> None:
    if not await _ensure_private_chat(message):
        return

    profile = chat_service.build_profile(message.from_user)
    session = chat_service.get_or_create_active_session(profile)
    text = (
        "<b>ReMind в Telegram</b>\n"
        f"Активный чат: <code>{session.title}</code>\n\n"
        "Пиши сообщение как обычно.\n"
        "Команды: /new, /history, /current"
    )
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=primary_actions_keyboard(),
    )


@router.message(Command("new"))
@router.message(Command("reset"))
async def command_new_chat(message: Message, chat_service: TelegramChatService) -> None:
    if not await _ensure_private_chat(message):
        return

    profile = chat_service.build_profile(message.from_user)
    session = chat_service.create_new_session(profile)
    await message.answer(
        f"Создал новый чат.\nТекущий заголовок: {session.title}",
        reply_markup=primary_actions_keyboard(),
    )


@router.message(Command("history"))
async def command_history(message: Message, chat_service: TelegramChatService) -> None:
    if not await _ensure_private_chat(message):
        return

    profile = chat_service.build_profile(message.from_user)
    await _send_history(message, chat_service, profile.telegram_id)


@router.message(Command("current"))
async def command_current(message: Message, chat_service: TelegramChatService) -> None:
    if not await _ensure_private_chat(message):
        return

    profile = chat_service.build_profile(message.from_user)
    session = chat_service.get_or_create_active_session(profile)
    await message.answer(
        f"Текущий чат: {session.title}\nID: {session.session_id}",
        reply_markup=primary_actions_keyboard(),
    )


@router.callback_query(BotActionCallback.filter(F.action == "new"))
async def callback_new_chat(
    callback: CallbackQuery, chat_service: TelegramChatService
) -> None:
    if not await _ensure_private_chat(callback.message):
        return

    profile = chat_service.build_profile(callback.from_user)
    session = chat_service.create_new_session(profile)
    await callback.message.answer(
        f"Создал новый чат.\nТекущий заголовок: {session.title}",
        reply_markup=primary_actions_keyboard(),
    )


@router.callback_query(BotActionCallback.filter(F.action == "history"))
async def callback_history(
    callback: CallbackQuery, chat_service: TelegramChatService
) -> None:
    if not await _ensure_private_chat(callback.message):
        return

    await _send_history(
        callback.message,
        chat_service,
        callback.from_user.id,
    )


@router.callback_query(SessionSwitchCallback.filter())
async def callback_switch_session(
    callback: CallbackQuery,
    callback_data: SessionSwitchCallback,
    chat_service: TelegramChatService,
) -> None:
    if not await _ensure_private_chat(callback.message):
        return

    session = chat_service.switch_session(callback.from_user.id, callback_data.session_id)
    if session is None:
        await callback.message.answer(
            "Не нашел этот чат в истории.",
            reply_markup=primary_actions_keyboard(),
        )
        return

    await callback.message.answer(
        f"Переключил на чат: {session.title}",
        reply_markup=primary_actions_keyboard(),
    )


@router.message(F.text)
async def handle_text_message(message: Message, chat_service: TelegramChatService) -> None:
    if not await _ensure_private_chat(message):
        return

    text = (message.text or "").strip()
    if not text:
        return
    if text.startswith("/"):
        await message.answer("Доступные команды: /start, /new, /history, /current")
        return

    profile = chat_service.build_profile(message.from_user)
    lock = chat_service.get_generation_lock(profile.telegram_id)
    if lock.locked():
        await message.answer("Сначала дождись завершения текущего ответа.")
        return

    session = chat_service.get_or_create_active_session(profile)
    progress_message = await message.answer(
        "Думаю...",
        reply_markup=primary_actions_keyboard(),
    )

    full_reply = ""
    final_event: dict[str, object] = {}
    last_edit_at = 0.0
    last_rendered = "Думаю..."

    async with lock:
        try:
            async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
                async for event in chat_service.stream_chat(profile, text, session.session_id):
                    if event.get("final"):
                        final_event = event
                        break

                    reply_part = str(event.get("reply_part") or "")
                    if reply_part:
                        full_reply += reply_part

                    preview = _build_stream_preview(full_reply)
                    now = time.monotonic()
                    if preview != last_rendered and now - last_edit_at >= STREAM_EDIT_INTERVAL_SECONDS:
                        await _safe_edit_message(progress_message, preview)
                        last_rendered = preview
                        last_edit_at = now
        except Exception:
            logger.exception("Telegram bot failed to generate reply for user %s", profile.telegram_id)
            await _safe_edit_message(
                progress_message,
                "Не удалось получить ответ от модели. Попробуй еще раз.",
            )
            return

    final_reply = str(final_event.get("reply") or full_reply or "").strip()
    if not final_reply:
        final_reply = "Модель вернула пустой ответ."

    await _deliver_final_reply(progress_message, message, final_reply)


@router.message()
async def handle_unsupported_message(message: Message) -> None:
    if not await _ensure_private_chat(message):
        return

    await message.answer(
        "Пока поддерживаются только текстовые сообщения.",
        reply_markup=primary_actions_keyboard(),
    )


async def _send_history(
    message: Message,
    chat_service: TelegramChatService,
    telegram_id: int,
) -> None:
    sessions = chat_service.list_sessions(telegram_id)
    active_session_id = chat_service.get_active_session_id(telegram_id)
    if not sessions:
        await message.answer(
            "История пока пустая. Отправь первое сообщение.",
            reply_markup=primary_actions_keyboard(),
        )
        return

    await message.answer(
        _format_history_text(sessions, active_session_id),
        reply_markup=history_keyboard(sessions, active_session_id),
    )


def _format_history_text(
    sessions: Iterable[TelegramSessionSummary], active_session_id: str | None
) -> str:
    lines = ["Последние чаты:"]
    for session in sessions:
        marker = "•" if session.session_id == active_session_id else " "
        preview = f" — {session.preview}" if session.preview else ""
        lines.append(f"{marker} {session.title}{preview}")
    return "\n".join(lines)


def _build_stream_preview(text: str) -> str:
    if not text:
        return "Думаю..."
    if len(text) <= STREAM_PREVIEW_LIMIT:
        return text
    return text[:STREAM_PREVIEW_LIMIT] + "\n\n..."


async def _deliver_final_reply(
    progress_message: Message,
    source_message: Message,
    final_reply: str,
) -> None:
    chunks = _split_text(final_reply, TELEGRAM_MESSAGE_LIMIT)
    if not chunks:
        chunks = ["Модель вернула пустой ответ."]

    await _safe_edit_message(progress_message, chunks[0], reply_markup=primary_actions_keyboard())
    for chunk in chunks[1:]:
        await source_message.answer(chunk)


def _split_text(text: str, max_length: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _safe_edit_message(
    message: Message,
    text: str,
    reply_markup=None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if "message is not modified" in error_text:
            return
        logger.debug("Telegram edit failed: %s", exc)


async def _ensure_private_chat(message: Message | None) -> bool:
    if message is None:
        return False
    if message.chat.type == ChatType.PRIVATE:
        return True
    await message.answer("Используй бота в личных сообщениях, чтобы история не смешивалась.")
    return False
