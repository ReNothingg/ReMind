from __future__ import annotations

from app_factory import create_app
from services.telegram_bot import run_telegram_bot

if __name__ == "__main__":
    run_telegram_bot(create_app())
