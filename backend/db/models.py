from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

from backend.auth.accounts import (
    _telegram_bot_ready,
    _user_auth_methods,
    get_account_restriction,
    is_super_admin_user,
    is_telegram_placeholder_email,
)

db: Any = SQLAlchemy()


REMOVED_SETTINGS_DATA_KEYS = frozenset(
    {
        "personalization_nickname",
        "autocomplete",
        "autoscroll",
        "renderUserMarkdown",
        "autoSave",
    }
)


def sanitize_settings_data(raw_settings: Any) -> dict[str, Any]:
    from backend.agent_profile import normalize_agent_runtime

    if not isinstance(raw_settings, dict):
        return {}
    settings = {
        key: value for key, value in raw_settings.items() if key not in REMOVED_SETTINGS_DATA_KEYS
    }
    if "agentRuntime" in settings:
        settings["agentRuntime"] = normalize_agent_runtime(settings["agentRuntime"])
    return settings


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True)
    is_confirmed = db.Column(db.Boolean, default=False)
    confirmation_token = db.Column(db.String(100), nullable=True)
    confirmation_token_expires = db.Column(db.DateTime, nullable=True)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    oauth_provider = db.Column(db.String(20), nullable=True)
    oauth_id = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)
    moderation_reason = db.Column(db.String(280), nullable=True)
    ban_reason = db.Column(db.String(280), nullable=True)
    block_reason = db.Column(db.String(280), nullable=True)
    banned_until = db.Column(db.DateTime, nullable=True)
    blocked_until = db.Column(db.DateTime, nullable=True)
    auth_version = db.Column(db.Integer, nullable=False, default=0)
    auth_identities = db.relationship(
        "AuthIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    telegram_link_requests = db.relationship(
        "TelegramLinkRequest",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self):
        return f"<User {self.username}>"

    def to_dict(self):
        is_super_admin = is_super_admin_user(self)
        restriction = get_account_restriction(self)
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "email": None if is_telegram_placeholder_email(self) else self.email,
            "is_confirmed": self.is_confirmed,
            "is_admin": bool(self.is_admin or is_super_admin),
            "is_super_admin": is_super_admin,
            "is_banned": bool(restriction and restriction["type"] == "ban"),
            "is_blocked": bool(restriction and restriction["type"] == "block"),
            "moderation_reason": restriction["reason"] if restriction else None,
            "ban_reason": self.ban_reason,
            "block_reason": self.block_reason,
            "banned_until": self.banned_until.isoformat() if self.banned_until else None,
            "blocked_until": self.blocked_until.isoformat() if self.blocked_until else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "oauth_provider": self.oauth_provider,
            "auth_methods": _user_auth_methods(self),
            "telegram_bot_ready": _telegram_bot_ready(self),
        }


class PasswordResetChallenge(db.Model):
    __tablename__ = "password_reset_challenge"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(24), unique=True, nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AuthIdentity(db.Model):
    __tablename__ = "auth_identity"
    __table_args__ = (
        db.UniqueConstraint(
            "provider", "provider_user_id", name="uq_auth_identity_provider_subject"
        ),
        db.UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False)
    provider_user_id = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User", back_populates="auth_identities")


class AppleAuthChallenge(db.Model):
    __tablename__ = "apple_auth_challenge"

    id = db.Column(db.Integer, primary_key=True)
    challenge_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    nonce_hash = db.Column(db.String(64), nullable=False)
    flow = db.Column(db.String(12), nullable=False)
    mode = db.Column(db.String(12), nullable=False)
    link_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    redirect_to = db.Column(db.String(500), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AppleTokenReplay(db.Model):
    __tablename__ = "apple_token_replay"

    token_hash = db.Column(db.String(64), primary_key=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TelegramLinkRequest(db.Model):
    __tablename__ = "telegram_link_request"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(24), unique=True, nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime, nullable=True)
    failure_code = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User", back_populates="telegram_link_requests")


class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    theme = db.Column(db.String(20), default="dark")
    language = db.Column(db.String(10), default="ru")
    automatic_web_search = db.Column(
        db.Boolean,
        default=True,
        server_default=text("TRUE"),
        nullable=False,
    )
    settings_data = db.Column(db.Text, default="{}")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserSettings {self.user_id}>"

    def get_settings(self):
        try:
            parsed = json.loads(self.settings_data) if self.settings_data else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return sanitize_settings_data(parsed)

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "theme": self.theme,
            "language": self.language,
            "automatic_web_search": bool(self.automatic_web_search),
            "settings_data": self.get_settings(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReMindWorkspace(db.Model):
    __tablename__ = "remind_workspace"

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = db.Column(db.String(80), nullable=False)
    instructions = db.Column(db.Text, nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ReMindWorkspaceFile(db.Model):
    __tablename__ = "remind_workspace_file"
    __table_args__ = (
        db.UniqueConstraint("workspace_id", "name_key", name="uq_workspace_file_name"),
    )

    id = db.Column(db.String(32), primary_key=True)
    workspace_id = db.Column(
        db.String(32),
        db.ForeignKey("remind_workspace.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    storage_name = db.Column(db.String(48), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=False)
    name_key = db.Column(db.String(64), nullable=False)
    mime_type = db.Column(db.String(120), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class WorkspacePatchProposal(db.Model):
    __tablename__ = "workspace_patch_proposal"
    __table_args__ = (
        db.UniqueConstraint("chat_id", "request_id", name="uq_workspace_patch_request"),
        db.Index("ix_workspace_patch_owner_expires", "user_id", "expires_at"),
    )

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    workspace_id = db.Column(
        db.String(32), db.ForeignKey("remind_workspace.id", ondelete="CASCADE"), nullable=False
    )
    chat_id = db.Column(
        db.Integer, db.ForeignKey("user_chat_history.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id = db.Column(db.String(100), nullable=False)
    patch = db.Column(db.Text, nullable=False)
    base_revision = db.Column(db.String(64), nullable=False)
    changes = db.Column(db.JSON, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    applied_at = db.Column(db.DateTime)


class AutomationTask(db.Model):
    __tablename__ = "automation_task"
    __table_args__ = (db.Index("ix_automation_task_due", "enabled", "next_run_at"),)

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = db.Column(db.String(120), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    model = db.Column(db.String(200), nullable=False)
    web_search = db.Column(db.Boolean, nullable=False, default=False)
    workspace_id = db.Column(
        db.String(32), db.ForeignKey("remind_workspace.id", ondelete="SET NULL")
    )
    target_session_id = db.Column(db.String(100))
    timing = db.Column(db.JSON, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    next_run_at = db.Column(db.DateTime)
    last_requested_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AutomationRun(db.Model):
    __tablename__ = "automation_run"
    __table_args__ = (
        db.Index("ix_automation_run_queue", "status", "queued_at"),
        db.Index("ix_automation_run_task_time", "task_id", "queued_at"),
    )

    id = db.Column(db.String(32), primary_key=True)
    task_id = db.Column(
        db.String(32), db.ForeignKey("automation_task.id", ondelete="CASCADE"), nullable=False
    )
    status = db.Column(db.String(16), nullable=False)
    session_id = db.Column(db.String(100))
    occurrence_at = db.Column(db.DateTime, nullable=False)
    queued_at = db.Column(db.DateTime, nullable=False)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)
    error = db.Column(db.String(64))


class AutomationProposal(db.Model):
    __tablename__ = "automation_proposal"
    __table_args__ = (
        db.UniqueConstraint("user_id", "request_id", name="uq_automation_proposal_request"),
    )

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    operation = db.Column(db.String(12), nullable=False)
    task_id = db.Column(db.String(32))
    task_state = db.Column(db.String(64))
    changes = db.Column(db.JSON, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    applied_at = db.Column(db.DateTime)
    result = db.Column(db.JSON)


class AgentPlugin(db.Model):
    __tablename__ = "agent_plugin"

    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    plugin_id = db.Column(db.String(72), primary_key=True)
    manifest = db.Column(db.JSON)
    enabled = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AgentSkill(db.Model):
    __tablename__ = "agent_skill"
    __table_args__ = (
        db.UniqueConstraint("user_id", "scope", "name", name="uq_agent_skill_scope_name"),
    )

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    scope = db.Column(db.String(32), nullable=False)
    workspace_id = db.Column(
        db.String(32), db.ForeignKey("remind_workspace.id", ondelete="CASCADE"), index=True
    )
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    resources = db.Column(db.JSON, nullable=False)
    properties = db.Column(db.JSON, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ChatModelSelection(db.Model):
    __tablename__ = "chat_model_selection"

    chat_id = db.Column(
        db.Integer, db.ForeignKey("user_chat_history.id", ondelete="CASCADE"), primary_key=True
    )
    pending = db.Column(db.JSON(none_as_null=True))
    last_used = db.Column(db.JSON(none_as_null=True))
    last_request_order = db.Column(db.BigInteger())


class UserChatHistory(db.Model):
    __table_args__ = (
        db.UniqueConstraint("user_id", "session_id", name="uq_user_chat_history_user_session"),
        db.UniqueConstraint(
            "user_id",
            "external_ref_hash",
            name="uq_user_chat_history_user_external_ref",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    workspace_id = db.Column(
        db.String(32),
        db.ForeignKey(
            "remind_workspace.id", name="fk_user_chat_history_workspace_id", ondelete="SET NULL"
        ),
        index=True,
    )
    mind_id = db.Column(
        db.Integer, db.ForeignKey("mind.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title = db.Column(db.String(200), default="Новый чат")
    source = db.Column(
        db.String(32), default="web", server_default="web", nullable=False, index=True
    )
    external_ref_hash = db.Column(db.String(64), nullable=True, index=True)
    source_context_data = db.Column(db.Text, default="{}", nullable=False)
    messages_data = db.Column(db.Text, default="[]")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserChatHistory {self.session_id}>"

    def get_messages(self):
        try:
            return json.loads(self.messages_data) if self.messages_data else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_messages(self, messages):
        self.messages_data = json.dumps(messages, ensure_ascii=False)

    def get_source_context(self):
        try:
            parsed = json.loads(self.source_context_data) if self.source_context_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_source_context(self, value):
        self.source_context_data = json.dumps(
            value if isinstance(value, dict) else {}, ensure_ascii=False
        )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "mind_id": self.mind_id,
            "title": self.title,
            "source": self.source or "web",
            "messages": self.get_messages(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatContextCheckpoint(db.Model):
    __tablename__ = "chat_context_checkpoint"
    __table_args__ = (
        db.UniqueConstraint("chat_id", "prefix_digest", name="uq_chat_context_prefix"),
    )

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(
        db.Integer,
        db.ForeignKey("user_chat_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    covered_count = db.Column(db.Integer, nullable=False)
    prefix_digest = db.Column(db.String(64), nullable=False)
    excerpts = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ChatProviderReplay(db.Model):
    __tablename__ = "chat_provider_replay"

    chat_id = db.Column(
        db.Integer, db.ForeignKey("user_chat_history.id", ondelete="CASCADE"), primary_key=True
    )
    message_id = db.Column(db.String(120), primary_key=True)
    route_key = db.Column(db.String(64), nullable=False)
    history_digest = db.Column(db.String(64), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TelegramInlineResult(db.Model):
    __tablename__ = "telegram_inline_result"

    id = db.Column(db.Integer, primary_key=True)
    result_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.String(32), nullable=False, index=True)
    query_text = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(12), nullable=True)
    selected_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class AIResponseFeedback(db.Model):
    __tablename__ = "ai_response_feedback"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, index=True)
    message_client_id = db.Column(db.String(120), nullable=True)
    response_hash = db.Column(db.String(64), nullable=False, index=True)
    rating = db.Column(db.String(12), nullable=False, index=True)
    reason_codes_data = db.Column(db.Text, default="[]", nullable=False)
    comment = db.Column(db.Text, nullable=True)
    prompt_text = db.Column(db.Text, nullable=True)
    response_text = db.Column(db.Text, nullable=True)
    service_improvement_opt_in = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "session_id",
            "response_hash",
            name="uq_ai_feedback_user_session_response",
        ),
    )

    def get_reason_codes(self):
        try:
            parsed = json.loads(self.reason_codes_data) if self.reason_codes_data else []
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_reason_codes(self, reason_codes):
        self.reason_codes_data = json.dumps(reason_codes or [], ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message_client_id": self.message_client_id,
            "response_hash": self.response_hash,
            "rating": self.rating,
            "reason_codes": self.get_reason_codes(),
            "comment": self.comment,
            "prompt_text": self.prompt_text,
            "response_text": self.response_text,
            "service_improvement_opt_in": bool(self.service_improvement_opt_in),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ChatShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, unique=True, index=True)
    public_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "public_id": self.public_id,
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatGPTConnection(db.Model):
    __tablename__ = "chatgpt_connection"

    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    host_id = db.Column(db.String(64), nullable=False)
    credentials = db.Column(db.Text)
    pending = db.Column(db.Text)
    models = db.Column(db.JSON)
    catalog_time = db.Column(db.Integer, default=0, nullable=False)


class AgentWorkspaceSlot(db.Model):
    __tablename__ = "agent_workspace_slot"
    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), unique=True)
    workspace_id = db.Column(db.String(32), unique=True)
    generation = db.Column(db.Integer, nullable=False, default=0)
    mind_public_id = db.Column(db.String(128))
    codex_catalog = db.Column(db.JSON)
    codex_catalog_time = db.Column(db.Integer, nullable=False, default=0)


class AgentWorkspaceTicket(db.Model):
    __tablename__ = "agent_workspace_ticket"
    digest = db.Column(db.String(64), primary_key=True)
    slot_id = db.Column(
        db.Integer, db.ForeignKey("agent_workspace_slot.id", ondelete="CASCADE"), nullable=False
    )
    expires = db.Column(db.BigInteger, nullable=False, index=True)


class TelegramAgentSettings(db.Model):
    __tablename__ = "telegram_agent_settings"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    model = db.Column(db.String(200), nullable=False, default="base")
    mind_id = db.Column(db.String(128))
    service_tier = db.Column(db.String(16), nullable=False, default="standard")
    web_search = db.Column(db.Boolean, nullable=False, default=False)
    secretary_mode = db.Column(db.String(16), nullable=False, default="off")


class TelegramBusinessLink(db.Model):
    __tablename__ = "telegram_business_link"
    connection_id = db.Column(db.String(200), primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_user_id = db.Column(db.String(32), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False)
    can_reply = db.Column(db.Boolean, nullable=False)
    last_update = db.Column(db.BigInteger, nullable=False)


class TelegramBusinessDelivery(db.Model):
    __tablename__ = "telegram_business_delivery"
    connection_id = db.Column(
        db.String(200),
        db.ForeignKey("telegram_business_link.connection_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_id = db.Column(db.BigInteger, primary_key=True)
    message_id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class AgentProviderKey(db.Model):
    __tablename__ = "agent_provider_key"

    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    provider = db.Column(db.String(48), primary_key=True)
    secret = db.Column(db.Text, nullable=False)
    catalog = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Mind(db.Model):
    __tablename__ = "mind"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(280), nullable=False)
    instructions = db.Column(db.Text, nullable=False)
    starters_data = db.Column(db.Text, default="[]", nullable=False)
    allow_external_use = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    skill_ids = db.Column(db.JSON(none_as_null=True))
    custom_skills = db.Column(db.JSON(none_as_null=True))
    category = db.Column(db.String(50), default="general", nullable=False, index=True)
    visibility = db.Column(db.String(20), default="private", nullable=False, index=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_banned = db.Column(db.Boolean, default=False, nullable=False, index=True)
    moderation_reason = db.Column(db.String(280), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_starters(self):
        try:
            parsed = json.loads(self.starters_data) if self.starters_data else []
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_starters(self, starters):
        self.starters_data = json.dumps(starters or [], ensure_ascii=False)

    def to_dict(self, viewer_id=None, pinned=False):
        is_owner = bool(viewer_id is not None and self.user_id == viewer_id)
        return {
            "id": self.id,
            "public_id": self.public_id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions if is_owner or self.allow_external_use else "",
            "allow_external_use": bool(self.allow_external_use),
            "starters": self.get_starters(),
            "skill_ids": self.skill_ids if is_owner or self.skill_ids is None else [
                skill for skill in self.skill_ids if isinstance(skill, str) and not skill.startswith("skill:")
            ],
            "custom_skills": (self.custom_skills or [])
            if is_owner or self.allow_external_use
            else [],
            "custom_skill_names": [skill["name"] for skill in self.custom_skills or []],
            "category": self.category,
            "visibility": self.visibility,
            "is_verified": bool(self.is_verified),
            "is_system": bool(self.is_system),
            "is_featured": bool(self.is_featured),
            "is_banned": bool(self.is_banned),
            "moderation_reason": self.moderation_reason if is_owner else None,
            "is_owner": is_owner,
            "can_edit": is_owner and not self.is_system,
            "is_pinned": bool(pinned),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MindPin(db.Model):
    __tablename__ = "mind_pin"
    __table_args__ = (db.UniqueConstraint("user_id", "mind_id", name="uq_mind_pin_user_mind"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    mind_id = db.Column(db.Integer, db.ForeignKey("mind.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class GitHubInstallation(db.Model):
    __tablename__ = "github_installation"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "installation_id",
            name="uq_github_installation_user_installation",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    installation_id = db.Column(db.BigInteger, nullable=False, index=True)
    account_login = db.Column(db.String(120), nullable=False)
    account_html_url = db.Column(db.String(500), nullable=True)
    account_avatar_url = db.Column(db.String(500), nullable=True)
    target_type = db.Column(db.String(40), nullable=True)
    repository_selection = db.Column(db.String(40), nullable=True)
    permissions_data = db.Column(db.Text, default="{}", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_permissions(self):
        try:
            parsed = json.loads(self.permissions_data) if self.permissions_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_permissions(self, permissions):
        self.permissions_data = json.dumps(permissions or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "installation_id": self.installation_id,
            "account_login": self.account_login,
            "account_html_url": self.account_html_url,
            "account_avatar_url": self.account_avatar_url,
            "target_type": self.target_type,
            "repository_selection": self.repository_selection,
            "permissions": self.get_permissions(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GitHubAgentTask(db.Model):
    __tablename__ = "github_agent_task"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    installation_id = db.Column(db.BigInteger, nullable=False, index=True)
    repo_full_name = db.Column(db.String(260), nullable=False, index=True)
    base_branch = db.Column(db.String(260), nullable=False)
    branch_name = db.Column(db.String(260), nullable=True)
    task = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(40), default="planned", nullable=False, index=True)
    plan_data = db.Column(db.Text, default="{}", nullable=False)
    edits_data = db.Column(db.Text, default="{}", nullable=False)
    diff = db.Column(db.Text, nullable=True)
    pull_request_number = db.Column(db.Integer, nullable=True)
    pull_request_url = db.Column(db.String(500), nullable=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_plan(self):
        try:
            parsed = json.loads(self.plan_data) if self.plan_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_plan(self, plan):
        self.plan_data = json.dumps(plan or {}, ensure_ascii=False)

    def get_edits(self):
        try:
            parsed = json.loads(self.edits_data) if self.edits_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_edits(self, edits):
        self.edits_data = json.dumps(edits or {}, ensure_ascii=False)

    def to_dict(self, include_details=True):
        payload = {
            "id": self.public_id,
            "installation_id": self.installation_id,
            "repo_full_name": self.repo_full_name,
            "base_branch": self.base_branch,
            "branch_name": self.branch_name,
            "task": self.task,
            "status": self.status,
            "pull_request_number": self.pull_request_number,
            "pull_request_url": self.pull_request_url,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_details:
            payload["plan"] = self.get_plan()
            payload["edits"] = self.get_edits()
            payload["diff"] = self.diff
        return payload
