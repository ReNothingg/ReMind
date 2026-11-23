from __future__ import annotations

from backend.app_factory import create_app
from backend.services.telegram.bot import run_telegram_bot

if __name__ == "__main__":
    run_telegram_bot(create_app())
