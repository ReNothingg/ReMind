from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any

import redis
from cryptography.fernet import Fernet, InvalidToken
from redis.exceptions import RedisError, ResponseError

from config import (
    GITHUB_OAUTH_CREDENTIAL_TTL_SECONDS,
    GITHUB_OAUTH_ENCRYPTION_KEY,
    GITHUB_OAUTH_STATE_TTL_SECONDS,
    REDIS_URL,
    SECRET_KEY,
)

_STATE_KEY_PREFIX = "remind:github:oauth:state:"
_CREDENTIAL_KEY_PREFIX = "remind:github:oauth:credential:"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{20,256}$")
_GETDEL_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""


class GitHubOAuthFlowError(RuntimeError):
    """A secure OAuth flow could not be completed without exposing its credential."""


@dataclass(frozen=True, slots=True)
class GitHubOAuthStart:
    state: str
    flow_id: str


@dataclass(frozen=True, slots=True)
class GitHubOAuthState:
    flow_id: str
    after: str
    pending_installation_id: int | None


def _fernet_key(configured_key: str, secret_key: str | None) -> bytes:
    if configured_key:
        candidate = configured_key.encode("utf-8")
        try:
            Fernet(candidate)
        except (TypeError, ValueError) as exc:
            raise GitHubOAuthFlowError("GitHub OAuth encryption key is invalid.") from exc
        return candidate

    if not secret_key:
        raise GitHubOAuthFlowError("GitHub OAuth encryption key is not configured.")

    material = b"remind:github-oauth-flow:v1:\x00" + secret_key.encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


def _identifier(value: str | None) -> str:
    candidate = str(value or "").strip()
    return candidate if _IDENTIFIER_RE.fullmatch(candidate) else ""


class GitHubOAuthFlowStore:
    """Keeps short-lived GitHub OAuth credentials outside browser cookies."""

    def __init__(
        self,
        redis_client: Any,
        *,
        encryption_key: str = GITHUB_OAUTH_ENCRYPTION_KEY,
        secret_key: str | None = SECRET_KEY,
        state_ttl_seconds: int = GITHUB_OAUTH_STATE_TTL_SECONDS,
        credential_ttl_seconds: int = GITHUB_OAUTH_CREDENTIAL_TTL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._fernet = Fernet(_fernet_key(encryption_key, secret_key))
        self._state_ttl_seconds = max(60, int(state_ttl_seconds))
        self._credential_ttl_seconds = max(60, int(credential_ttl_seconds))

    @classmethod
    def from_config(cls) -> "GitHubOAuthFlowStore":
        return cls(redis.Redis.from_url(REDIS_URL, decode_responses=True))

    def start(
        self,
        user_id: int,
        *,
        after: str = "",
        pending_installation_id: int | None = None,
    ) -> GitHubOAuthStart:
        state = secrets.token_urlsafe(32)
        flow_id = secrets.token_urlsafe(32)
        payload = {
            "user_id": int(user_id),
            "flow_id": flow_id,
            "after": str(after or ""),
            "pending_installation_id": (
                int(pending_installation_id) if pending_installation_id is not None else None
            ),
        }
        self._set(
            self._state_key(state),
            json.dumps(payload, separators=(",", ":")),
            self._state_ttl_seconds,
        )
        return GitHubOAuthStart(state=state, flow_id=flow_id)

    def consume_state(self, state: str, user_id: int) -> GitHubOAuthState | None:
        state = _identifier(state)
        if not state:
            return None
        raw = self._getdel(self._state_key(state))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            stored_user_id = int(payload["user_id"])
            flow_id = _identifier(payload.get("flow_id"))
            pending = payload.get("pending_installation_id")
            pending_installation_id = int(pending) if pending is not None else None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if stored_user_id != int(user_id) or not flow_id:
            return None
        return GitHubOAuthState(
            flow_id=flow_id,
            after=str(payload.get("after") or ""),
            pending_installation_id=pending_installation_id,
        )

    def store_credential(self, flow_id: str, user_id: int, access_token: str) -> None:
        flow_id = _identifier(flow_id)
        token = str(access_token or "").strip()
        if not flow_id or not token:
            raise GitHubOAuthFlowError("GitHub OAuth credential is invalid.")
        payload = json.dumps(
            {"user_id": int(user_id), "access_token": token}, separators=(",", ":")
        )
        encrypted = self._fernet.encrypt(payload.encode("utf-8")).decode("ascii")
        self._set(self._credential_key(flow_id), encrypted, self._credential_ttl_seconds)

    def has_credential(self, flow_id: str, user_id: int) -> bool:
        return self._read_credential(flow_id, user_id) is not None

    def consume_credential(self, flow_id: str, user_id: int) -> str | None:
        flow_id = _identifier(flow_id)
        if not flow_id:
            return None
        raw = self._getdel(self._credential_key(flow_id))
        return self._decode_credential(raw, user_id)

    def discard_credential(self, flow_id: str | None) -> None:
        flow_id = _identifier(flow_id)
        if not flow_id:
            return
        try:
            self._redis.delete(self._credential_key(flow_id))
        except RedisError as exc:
            raise GitHubOAuthFlowError("Secure GitHub authorization store is unavailable.") from exc

    def _read_credential(self, flow_id: str, user_id: int) -> str | None:
        flow_id = _identifier(flow_id)
        if not flow_id:
            return None
        try:
            raw = self._redis.get(self._credential_key(flow_id))
        except RedisError as exc:
            raise GitHubOAuthFlowError("Secure GitHub authorization store is unavailable.") from exc
        return self._decode_credential(raw, user_id)

    def _decode_credential(self, raw: Any, user_id: int) -> str | None:
        if not raw:
            return None
        try:
            value = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            payload = json.loads(self._fernet.decrypt(value).decode("utf-8"))
            if int(payload["user_id"]) != int(user_id):
                return None
            token = str(payload["access_token"] or "").strip()
        except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return token or None

    def _set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            self._redis.set(key, value, ex=ttl_seconds)
        except RedisError as exc:
            raise GitHubOAuthFlowError("Secure GitHub authorization store is unavailable.") from exc

    def _getdel(self, key: str) -> Any:
        try:
            return self._redis.getdel(key)
        except AttributeError:
            return self._eval_getdel(key)
        except ResponseError:
            return self._eval_getdel(key)
        except RedisError as exc:
            raise GitHubOAuthFlowError("Secure GitHub authorization store is unavailable.") from exc

    def _eval_getdel(self, key: str) -> Any:
        try:
            return self._redis.eval(_GETDEL_SCRIPT, 1, key)
        except RedisError as exc:
            raise GitHubOAuthFlowError("Secure GitHub authorization store is unavailable.") from exc

    @staticmethod
    def _state_key(state: str) -> str:
        return f"{_STATE_KEY_PREFIX}{state}"

    @staticmethod
    def _credential_key(flow_id: str) -> str:
        return f"{_CREDENTIAL_KEY_PREFIX}{flow_id}"
