from config import (
    SERVER_THREADS,
    SERVER_CONNECTION_LIMIT,
    SERVER_CHANNEL_TIMEOUT,
)
from app_factory import create_app

if __name__ == "__main__":
    app = create_app()
    print("\n" + "=" * 60 + "\nReMind AI Server Running\n" + "=" * 60)
    try:
        from waitress import serve

        serve(
            app,
            host="0.0.0.0",
            port=5000,
            threads=SERVER_THREADS,
            connection_limit=SERVER_CONNECTION_LIMIT,
            channel_timeout=SERVER_CHANNEL_TIMEOUT,
        )
    except ImportError:
        app.run(host="0.0.0.0", port=5000, debug=False)