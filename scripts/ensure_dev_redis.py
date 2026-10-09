from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import redis
from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if os.getenv("LOAD_DOTENV", "true").lower() not in {"0", "false", "no"}:
        load_dotenv(os.getenv("DOTENV_PATH", str(root / ".env")))
    redis_url = os.getenv("REDIS_URL", "")
    parsed = urlparse(redis_url)
    if parsed.scheme != "redis" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return
    if parsed.username not in {None, "", "default"}:
        return
    client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        client.ping()
        print("[redis] Local Redis is ready", flush=True)
        return
    except redis.AuthenticationError:
        print("[redis] Existing Redis rejected the configured credentials", flush=True)
        return
    except redis.ConnectionError:
        pass
    finally:
        client.close()

    executable = shutil.which("redis-server")
    if not executable:
        print(
            "[redis] redis-server is missing; install Redis for persistent local storage",
            flush=True,
        )
        return
    data_dir = root / "database" / "dev-redis"
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    port = parsed.port or 6379
    # Redis URL passwords are percent-encoded; use the client's decoded connection settings.
    password = client.connection_pool.connection_kwargs.get("password")
    if not password:
        print("[redis] Set a password in REDIS_URL before starting local Redis", flush=True)
        return

    def quote(value) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    config = "\n".join(
        [
            "bind 127.0.0.1 ::1",
            "protected-mode yes",
            f"port {port}",
            "daemonize yes",
            f"dir {quote(data_dir)}",
            f"pidfile {quote(data_dir / 'redis.pid')}",
            f"logfile {quote(data_dir / 'redis.log')}",
            "appendonly yes",
            f"requirepass {quote(password)}",
            "",
        ]
    )
    # Feed credentials through stdin, never command arguments or a config file.
    result = subprocess.run(
        [executable, "-"], input=config, text=True, capture_output=True, timeout=10, check=False
    )
    if result.returncode:
        print("[redis] Local Redis could not start; check its local log", flush=True)
        return
    client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        for _ in range(20):
            try:
                client.ping()
                print(
                    "[redis] Started local Redis with authentication and persistent storage",
                    flush=True,
                )
                return
            except redis.ConnectionError:
                time.sleep(0.1)
        print("[redis] Local Redis did not become ready", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
