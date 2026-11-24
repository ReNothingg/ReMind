from __future__ import annotations

import base64
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from backend.auth.accounts import is_account_disabled
from backend.db.models import AgentWorkspaceSlot, AgentWorkspaceTicket, User, db
from backend.errors import ApiError
from backend.security.provider_secrets import provider_master_key

ISSUER = "remind-workspace"
AUDIENCE = "remind-agent-slot"


def capacity():
    try:
        return min(256, max(0, int(os.getenv("AGENT_SLOT_COUNT", "0"))))
    except ValueError:
        return 0


def existing(owner):
    return AgentWorkspaceSlot.query.filter_by(user_id=owner).first() if owner else None


def reserve(owner):
    user = db.session.get(User, owner)
    if not user or is_account_disabled(user):
        raise ApiError("access_denied", status=403, code="access_denied")
    count = capacity()
    if not count:
        raise ApiError("workspace_not_configured", status=503, code="workspace_not_configured")
    row = existing(owner)
    if row:
        return row
    for index in range(1, count + 1):
        if db.session.get(AgentWorkspaceSlot, index) is None:
            try:
                with db.session.begin_nested():
                    db.session.add(AgentWorkspaceSlot(id=index))
                    db.session.flush()
            except IntegrityError:
                pass
        try:
            changed = db.session.execute(
                update(AgentWorkspaceSlot)
                .where(AgentWorkspaceSlot.id == index, AgentWorkspaceSlot.user_id.is_(None))
                .values(
                    user_id=owner,
                    workspace_id=secrets.token_hex(16),
                    generation=AgentWorkspaceSlot.generation + 1,
                    codex_catalog=None,
                    codex_catalog_time=0,
                )
            )
            db.session.commit()
            if changed.rowcount:
                return db.session.get(AgentWorkspaceSlot, index)
        except IntegrityError:
            db.session.rollback()
            row = existing(owner)
            if row:
                return row
    assigned = existing(owner)
    if assigned is not None:
        return assigned
    raise ApiError("workspace_pool_full", status=503, code="workspace_pool_full")


@dataclass(frozen=True)
class LeaseIdentity:
    id: int
    workspace_id: str
    generation: int
    user_id: int | None


def _lock_owner(owner):
    locked = db.session.execute(
        update(AgentWorkspaceSlot).where(AgentWorkspaceSlot.user_id == owner).values(user_id=owner)
    )
    if not locked.rowcount:
        return None
    return AgentWorkspaceSlot.query.filter_by(user_id=owner).populate_existing().one()


def _identity(slot_id, owner):
    row = db.session.execute(
        db.select(
            AgentWorkspaceSlot.id,
            AgentWorkspaceSlot.workspace_id,
            AgentWorkspaceSlot.generation,
            AgentWorkspaceSlot.user_id,
        ).where(AgentWorkspaceSlot.id == slot_id, AgentWorkspaceSlot.user_id == owner)
    ).first()
    if row is None:
        raise ApiError("workspace_session_expired", status=401, code="workspace_session_expired")
    return LeaseIdentity(*row)


def _signing_key():
    seed = hmac.digest(
        base64.urlsafe_b64decode(provider_master_key()),
        b"ReMind agent slot signatures v1",
        "sha256",
    )
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key():
    return (
        _signing_key()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def grant(slot, purpose, seconds=60, **extra):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "scope": purpose,
            "sub": slot.workspace_id,
            "slot": slot.id,
            "gen": slot.generation,
            "owner": slot.user_id,
            "iat": now,
            "exp": now + seconds,
            "jti": secrets.token_urlsafe(24),
            **extra,
        },
        _signing_key(),
        algorithm="EdDSA",
    )


def verify(token, purpose):
    try:
        claims = jwt.decode(
            token,
            _signing_key().public_key(),
            algorithms=["EdDSA"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "slot", "gen", "scope", "jti"]},
        )
        if claims["scope"] != purpose:
            raise ValueError()
        row = db.session.get(AgentWorkspaceSlot, claims["slot"], populate_existing=True)
        if (
            not row
            or not row.user_id
            or row.user_id != claims.get("owner")
            or row.workspace_id != claims["sub"]
            or row.generation != claims["gen"]
        ):
            raise ValueError()
        user = db.session.get(User, row.user_id)
        if not user or is_account_disabled(user):
            raise ValueError()
        return row, claims
    except (jwt.PyJWTError, ValueError, TypeError) as error:
        raise ApiError(
            "workspace_session_expired", status=401, code="workspace_session_expired"
        ) from error


def target(slot, path):
    base = os.getenv("AGENT_SLOT_ROUTER", "http://agent-router:8090").rstrip("/")
    return f"{base}/slots/{slot.id}/__agent/{path}"


def rpc(slot, op, payload=None, *, owner, stream=False, timeout=12):
    slot = _identity(slot.id, owner)
    body = payload or {}
    headers = {"Authorization": "Bearer " + grant(slot, "rpc", 120, op=op)}
    try:
        response = requests.post(
            target(slot, op),
            json=body,
            headers=headers,
            stream=stream,
            timeout=(4, timeout),
            allow_redirects=False,
        )
        if response.status_code != 200:
            try:
                code = response.json().get("error")
            except (ValueError, AttributeError):
                code = None
            response.close()
            statuses = {
                "chatgpt_reconnect": 401,
                "model_speed_unavailable": 400,
                "model_access_denied": 403,
                "chatgpt_quota": 429,
            }
            if code in statuses:
                raise ApiError(code, status=statuses[code], code=code)
            raise ApiError(
                "workspace_runtime_unavailable", status=503, code="workspace_runtime_unavailable"
            )
        if stream:
            return response
        with response:
            return response.json()
    except (requests.RequestException, ValueError) as error:
        raise ApiError(
            "workspace_runtime_unavailable", status=503, code="workspace_runtime_unavailable"
        ) from error


def release(owner):
    slot = _lock_owner(owner)
    if not slot:
        return None
    removal = {"url": target(slot, "erase"), "token": grant(slot, "rpc", 120, op="erase")}
    AgentWorkspaceTicket.query.filter_by(slot_id=slot.id).delete()
    slot.user_id, slot.workspace_id, slot.codex_catalog, slot.codex_catalog_time = (
        None,
        None,
        None,
        0,
    )
    slot.mind_public_id = None
    slot.generation += 1
    return removal


def notify_removal(removal):
    if not removal:
        return
    try:
        with requests.post(
            removal["url"],
            json={},
            headers={"Authorization": "Bearer " + removal["token"]},
            timeout=(2, 4),
            allow_redirects=False,
        ):
            pass
    except requests.RequestException:
        pass


def cleanup_instruction(data):
    if (
        not isinstance(data, dict)
        or type(data.get("slot")) is not int
        or type(data.get("generation")) is not int
        or not isinstance(data.get("workspace"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", data["workspace"])
    ):
        return None
    row = db.session.get(AgentWorkspaceSlot, data["slot"])
    if not row or row.generation <= data["generation"] or row.workspace_id == data["workspace"]:
        return None
    retired = LeaseIdentity(row.id, data["workspace"], data["generation"], None)
    return grant(retired, "rpc", 90, op="erase")
