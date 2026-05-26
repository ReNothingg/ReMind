from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from app_factory import create_app
from config import TELEGRAM_BOT_TOKEN
from services.telegram_chat_history import TelegramChatHistoryStore
from telegram_bot.handlers import router
from telegram_bot.service import TelegramChatService


def build_bot() -> Bot:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")
    return Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(
            link_preview_is_disabled=True,
        ),
    )


def build_dispatcher(chat_service: TelegramChatService) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    dispatcher["chat_service"] = chat_service
    dispatcher.startup.register(_on_startup)
    return dispatcher


async def _on_startup(bot: Bot, **_: object) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запуск бота"),
            BotCommand(command="new", description="Новый чат"),
            BotCommand(command="history", description="Последние чаты"),
            BotCommand(command="current", description="Текущий чат"),
        ]
    )


async def run_polling() -> None:
    flask_app = create_app()
    session_store = TelegramChatHistoryStore()
    chat_service = TelegramChatService(flask_app=flask_app, session_store=session_store)
    bot = build_bot()
    dispatcher = build_dispatcher(chat_service)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(
            bot,
            chat_service=chat_service,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
