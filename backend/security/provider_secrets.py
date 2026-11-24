import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.fernet import Fernet
from flask import current_app

from backend.config import DB_PATH


def provider_master_key():
    configured = os.getenv("PROVIDER_ENCRYPTION_KEY") or os.getenv("CHATGPT_ENCRYPTION_KEY")
    if configured:
        return configured.encode()
    folder = Path(current_app.config.get("CHATGPT_KEY_DIR", DB_PATH))
    path = folder / ".chatgpt-key"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=folder) as temporary:
            temporary.write(Fernet.generate_key())
            temporary.flush()
            os.fsync(temporary.fileno())
            try:
                os.link(temporary.name, path)
            except FileExistsError:
                pass
    return path.read_bytes()


def encrypt_provider_data(data):
    return Fernet(provider_master_key()).encrypt(json.dumps(data).encode()).decode()


def decrypt_provider_data(value):
    return json.loads(Fernet(provider_master_key()).decrypt(value.encode())) if value else {}
