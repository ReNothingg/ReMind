import logging
import os

from app_factory import create_app
from config import (
    SERVER_CHANNEL_TIMEOUT,
    SERVER_CONNECTION_LIMIT,
    SERVER_THREADS,
)

if __name__ == "__main__":
    app = create_app()
    bind_host = os.getenv("APP_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    print("\n" + "=" * 60 + "\nReMind AI Server Running\n" + "=" * 60)
    try:
        from waitress import serve  # type: ignore[import-untyped]

        try:
            # Waitress access records include raw targets, which may contain OAuth or
            # account-action tokens. Application logs retain safe route templates.
            logging.getLogger("waitress").setLevel(logging.WARNING)
            serve(
                app,
                host=bind_host,
                port=5000,
                threads=SERVER_THREADS,
                connection_limit=SERVER_CONNECTION_LIMIT,
                channel_timeout=SERVER_CHANNEL_TIMEOUT,
            )
        except KeyboardInterrupt:
            print("\nReMind AI Server stopped")
    except ImportError:
        try:
            logging.getLogger("werkzeug").setLevel(logging.WARNING)
            app.run(host=bind_host, port=5000, debug=False)
        except KeyboardInterrupt:
            print("\nReMind AI Server stopped")
