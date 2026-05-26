from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.telegram_chat_history import TelegramSessionSummary
from telegram_bot.callbacks import BotActionCallback, SessionSwitchCallback


def primary_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Новый чат", callback_data=BotActionCallback(action="new").pack())
    builder.button(text="История", callback_data=BotActionCallback(action="history").pack())
    builder.adjust(2)
    return builder.as_markup()


def history_keyboard(
    sessions: list[TelegramSessionSummary], active_session_id: str | None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for session in sessions:
        title = session.title or "Без названия"
        marker = "• " if session.session_id == active_session_id else ""
        builder.button(
            text=f"{marker}{title[:40]}",
            callback_data=SessionSwitchCallback(session_id=session.session_id).pack(),
        )
    builder.button(text="Новый чат", callback_data=BotActionCallback(action="new").pack())
    builder.adjust(1)
    return builder.as_markup()
