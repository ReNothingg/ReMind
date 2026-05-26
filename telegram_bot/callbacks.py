from aiogram.filters.callback_data import CallbackData


class BotActionCallback(CallbackData, prefix="bot"):
    action: str


class SessionSwitchCallback(CallbackData, prefix="session"):
    session_id: str
