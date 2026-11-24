from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import time
import uuid
from urllib.parse import urlencode, urlsplit

import jwt
import requests
from cryptography.fernet import InvalidToken
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from backend.ai_engine.errors import ProviderRequestError
from backend.db.models import ChatGPTConnection, db
from backend.security.provider_secrets import decrypt_provider_data as _read
from backend.security.provider_secrets import encrypt_provider_data as _pack
from backend.services.agent_models import capabilities

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN_ENDPOINT = f"{ISSUER}/api/accounts/oauth/token"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {DIRECT_SCOPE}"
MODEL_PREFIX = "chatgpt/"
MODEL_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}")
_keys = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", timeout=6)


def configuration():
    from backend.config import BACKEND_URL, IS_PRODUCTION

    local_dev = not IS_PRODUCTION or os.getenv("REMIND_LOCAL_DEV") == "1"
    redirect_uri = os.getenv(
        "CHATGPT_REDIRECT_URI", "http://127.0.0.1:5173/auth/callback" if local_dev else ""
    )
    client_id = os.getenv("CHATGPT_CLIENT_ID", "").strip()
    parsed = urlsplit(redirect_uri)
    local = parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
    if local and IS_PRODUCTION and not local_dev and BACKEND_URL and urlsplit(BACKEND_URL).hostname not in {"127.0.0.1","localhost","::1"}:
        return None
    hosted = parsed.scheme == "https" and parsed.hostname and client_id
    if (
        not (local or hosted)
        or parsed.path != "/auth/callback"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return None
    if client_id == "dynamic_agent_client":
        return None
    return redirect_uri, client_id


def _locked(user_id, *, create=False):
    if create and db.session.get(ChatGPTConnection, user_id) is None:
        try:
            with db.session.begin_nested():
                db.session.add(
                    ChatGPTConnection(user_id=user_id, host_id=f"urn:uuid:{uuid.uuid4()}")
                )
                db.session.flush()
        except IntegrityError:
            pass
    db.session.execute(
        update(ChatGPTConnection)
        .where(ChatGPTConnection.user_id == user_id)
        .values(host_id=ChatGPTConnection.host_id)
    )
    return db.session.get(ChatGPTConnection, user_id, populate_existing=True)


def status(user_id):
    row = db.session.get(ChatGPTConnection, user_id)
    record = _read(row.credentials) if row else {}
    config = configuration()
    return {
        "configured": bool(config),
        "origin": config[0].removesuffix("/auth/callback") if config else None,
        "registered": bool(record.get("client_id")),
        "connected": bool(record.get("access_token") and DIRECT_SCOPE in record.get("scopes", [])),
        "email": record.get("email") if record.get("access_token") else None,
        "consent_required": bool(
            record.get("access_token") and DIRECT_SCOPE not in record.get("scopes", [])
        ),
    }


def start_login(user_id, browser_state, *, different_account=False):
    config = configuration()
    if not config:
        raise ProviderRequestError("provider_not_configured")
    redirect_uri, hosted_client = config
    row = _locked(user_id, create=True)
    record = _read(row.credentials)
    if different_account:
        if record.get("access_token"):
            raise ProviderRequestError("chatgpt_login_failed", 409)
        record = {}
    client_id = hosted_client or record.get("client_id") or "dynamic_agent_client"
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(32)
    row.pending = _pack(
        {
            "state": browser_state,
            "nonce": nonce,
            "verifier": verifier,
            "uri": redirect_uri,
            "client_id": client_id,
            "different_account": different_account,
            "expires": time.time() + 600,
        }
    )
    args = {
        "client_id": client_id,
        "ext_agent_host_id": row.host_id,
        "response_type": "code",
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": browser_state,
        "nonce": nonce,
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("="),
    }
    if client_id == "dynamic_agent_client":
        args["agent_name_hint"] = "ReMind"
    elif record.get("access_token") and DIRECT_SCOPE not in record.get("scopes", []):
        args["prompt"] = "consent"
    db.session.commit()
    return f"{ISSUER}/api/accounts/authorize?{urlencode(args)}"


def _client_auth(client_id):
    secret = (
        os.getenv("CHATGPT_CLIENT_SECRET") if client_id == os.getenv("CHATGPT_CLIENT_ID") else None
    )
    return (client_id, secret) if secret else None


def _token_request(params):
    try:
        with requests.post(
            TOKEN_ENDPOINT,
            data={**params, "resource": RESOURCE},
            auth=_client_auth(params["client_id"]),
            timeout=(4, 8),
            allow_redirects=False,
        ) as response:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            if response.status_code != 200:
                error = data.get("error")
                code = error.get("code") if isinstance(error, dict) else error
                if code in (
                    "invalid_grant",
                    "invalid_refresh_token",
                    "token_expired",
                    "refresh_token_expired",
                    "refresh_token_invalidated",
                    "refresh_token_reused",
                ):
                    raise ProviderRequestError("chatgpt_reconnect", 401)
                raise ProviderRequestError("provider_unavailable")
            if (
                not isinstance(data.get("access_token"), str)
                or not data["access_token"]
                or int(data.get("expires_in", 0)) <= 0
            ):
                raise ValueError()
            return data
    except (requests.RequestException, ValueError, TypeError) as error:
        raise ProviderRequestError("provider_unavailable") from error


def _update_tokens(record, data):
    record.update(access_token=data["access_token"], expires=time.time() + int(data["expires_in"]))
    for key in ("id_token", "refresh_token"):
        if data.get(key):
            record[key] = data[key]
    if isinstance(data.get("scope"), str):
        record["scopes"] = data["scope"].split()


def complete_login(user_id, browser_state, params):
    row = _locked(user_id)
    pending = _read(row.pending) if row else {}
    if (
        pending.get("expires", 0) < time.time()
        or not browser_state
        or not secrets.compare_digest(browser_state, pending["state"])
        or not secrets.compare_digest(str(params.get("state", "")), pending["state"])
    ):
        raise ProviderRequestError("chatgpt_login_failed", 400)
    state_marker = _pack({"claimed": secrets.token_urlsafe(32)})
    row.pending = state_marker
    db.session.commit()
    if params.get("error") or not params.get("code"):
        raise ProviderRequestError("chatgpt_login_failed", 400)
    issued = params.get("client_id") or pending["client_id"]
    if (
        not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", issued)
        or issued == "dynamic_agent_client"
        or pending["client_id"] not in (issued, "dynamic_agent_client")
    ):
        raise ProviderRequestError("chatgpt_login_failed", 400)
    data = _token_request(
        {
            "grant_type": "authorization_code",
            "code": params["code"],
            "client_id": issued,
            "code_verifier": pending["verifier"],
            "redirect_uri": pending["uri"],
        }
    )
    try:
        token = data["id_token"]
        key = _keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=issued,
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iss", "aud", "nonce"]},
        )
        if not secrets.compare_digest(claims["nonce"], pending["nonce"]):
            raise ValueError()
        audiences = claims["aud"]
        if ("azp" in claims or (isinstance(audiences, list) and len(audiences) > 1)) and claims.get(
            "azp"
        ) != issued:
            raise ValueError()
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
        raise ProviderRequestError("chatgpt_login_failed", 400) from error
    row = _locked(user_id)
    if not row or row.pending != state_marker:
        raise ProviderRequestError("chatgpt_login_failed", 409)
    previous = _read(row.credentials)
    if (
        not pending.get("different_account")
        and previous.get("sub")
        and previous["sub"] != claims["sub"]
    ):
        raise ProviderRequestError("chatgpt_login_failed", 400)
    record = {"client_id": issued, "sub": claims["sub"], "email": claims.get("email"), "scopes": []}
    _update_tokens(record, data)
    row.credentials, row.catalog_time, row.models = _pack(record), 0, None
    row.pending = None
    db.session.commit()


def _grant(user_id):
    row = db.session.get(ChatGPTConnection, user_id, populate_existing=True) if user_id else None
    record = _read(row.credentials) if row else {}
    if DIRECT_SCOPE not in record.get("scopes", []):
        raise ProviderRequestError("chatgpt_reconnect", 403)
    if record.get("expires", 0) > time.time() + 45:
        return record["access_token"], row.credentials
    row = _locked(user_id)
    record = _read(row.credentials) if row else {}
    if DIRECT_SCOPE not in record.get("scopes", []) or not record.get("refresh_token"):
        db.session.rollback()
        raise ProviderRequestError("chatgpt_reconnect", 401)
    if record.get("expires", 0) <= time.time() + 45:
        try:
            data = _token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": record["client_id"],
                    "refresh_token": record["refresh_token"],
                }
            )
        except ProviderRequestError as error:
            if error.code == "chatgpt_reconnect":
                row.credentials = _pack({key: record[key] for key in ("client_id", "sub")})
                row.models, row.catalog_time = None, 0
                db.session.commit()
            else:
                db.session.rollback()
            raise
        _update_tokens(record, data)
        row.credentials = _pack(record)
    snapshot = row.credentials
    db.session.commit()
    if DIRECT_SCOPE not in record["scopes"]:
        raise ProviderRequestError("chatgpt_reconnect", 403)
    return record["access_token"], snapshot


def access_token(user_id):
    return _grant(user_id)[0]


def replay_access(user_id):
    token, snapshot = _grant(user_id)
    identity = _read(snapshot)
    client = identity.get("client_id")
    subject = identity.get("sub")
    return token, (client, subject) if client and subject else None


def list_models(user_id):
    if not user_id or not configuration():
        return []
    row = db.session.get(ChatGPTConnection, user_id, populate_existing=True)
    if not row or not row.credentials:
        return []
    if row.catalog_time > time.time() - 90 and row.models is not None:
        return row.models
    try:
        token, snapshot = _grant(user_id)
        with requests.get(
            f"{RESOURCE}/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=(3, 6),
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                return []
            entries = response.json()["models"]
        models = [
            {
                "id": MODEL_PREFIX + item["slug"],
                "title": item.get("display_name") or item["slug"],
                "subtitle": "",
                "subtitleKey": "chatgptAccount.model",
                "stage": "release",
                "source":"chatgpt", "provider":"openai",
                **capabilities(item),
            }
            for item in entries
            if isinstance(item, dict)
            and item.get("visibility") == "list"
            and isinstance(item.get("slug"), str)
            and MODEL_SLUG.fullmatch(item["slug"])
        ]
        saved = db.session.execute(
            update(ChatGPTConnection)
            .where(ChatGPTConnection.user_id == user_id, ChatGPTConnection.credentials == snapshot)
            .values(models=models, catalog_time=int(time.time()))
        )
        db.session.commit()
        return models if saved.rowcount else []
    except (ProviderRequestError, requests.RequestException, ValueError, KeyError, TypeError):
        return []


def disconnect(user_id):
    row = _locked(user_id)
    record = _read(row.credentials) if row else {}
    if row:
        row.credentials = _pack({key: record[key] for key in ("client_id", "sub") if key in record})
        row.pending, row.models, row.catalog_time = None, None, 0
    db.session.commit()
    return _revoke(record)


def remove_registration(user_id):
    return db.session.execute(
        delete(ChatGPTConnection)
        .where(ChatGPTConnection.user_id == user_id)
        .returning(ChatGPTConnection.credentials)
    ).first()


def revoke_removed(registration):
    if registration is None:
        return True
    try:
        return _revoke(_read(registration[0]))
    except (InvalidToken, OSError, ValueError):
        return False


def _revoke(record):
    revoked = True
    if record.get("refresh_token"):
        revoked = False
        try:
            with requests.get(
                f"{ISSUER}/.well-known/openid-configuration", timeout=5, allow_redirects=False
            ) as discovery:
                uri = discovery.json()["revocation_endpoint"]
            if urlsplit(uri).scheme == "https" and urlsplit(uri).netloc == "auth.openai.com":
                with requests.post(
                    uri,
                    data={
                        "token": record["refresh_token"],
                        "token_type_hint": "refresh_token",
                        "client_id": record["client_id"],
                    },
                    auth=_client_auth(record["client_id"]),
                    timeout=5,
                    allow_redirects=False,
                ) as reply:
                    revoked = reply.status_code == 200
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass
    return revoked
