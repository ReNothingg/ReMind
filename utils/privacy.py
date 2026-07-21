import hashlib
import os
from datetime import datetime
from pathlib import Path

from flask import current_app, has_app_context

from config import CHATS_FOLDER, CREATE_IMAGE_FOLDER, UPLOAD_FOLDER
from services.attachment_lifecycle import (
    collect_managed_references,
    delete_unreferenced_managed_files,
    merge_managed_references,
)
from utils.responses import logger

SERVICE_IMPROVEMENT_SETTING_KEY = "service_improvement_opt_in"


def anonymize_ip(ip_address):
    if not ip_address:
        return None

    if ":" in ip_address:  # IPv6
        parts = ip_address.split(":")
        if len(parts) > 2:
            return ":".join(parts[:3]) + "::0"
    else:  # IPv4
        parts = ip_address.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3]) + ".0"

    return None


def hash_for_logging(value, salt="remind_log"):
    if not value:
        return None
    combined = f"{salt}:{value}"
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


def get_user_data_locations(user_id):
    return {
        "database": [
            "user",
            "user_settings",
            "user_chat_history",
            "ai_response_feedback",
            "chat_share",
            "mind",
            "mind_pin",
            "github_installation",
            "github_agent_task",
        ],
        "files": {
            "chats": CHATS_FOLDER,
            "uploads": UPLOAD_FOLDER,
            "generated_images": CREATE_IMAGE_FOLDER,
        },
    }


def _configured_folder(config_key: str, fallback: Path) -> Path:
    if has_app_context():
        configured = current_app.config.get(config_key)
        if configured:
            return Path(configured)
    return fallback


def export_user_data(user_id):
    from utils.auth import (
        AIResponseFeedback,
        ChatShare,
        GitHubAgentTask,
        GitHubInstallation,
        Mind,
        MindPin,
        User,
        UserChatHistory,
        UserSettings,
        db,
    )

    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "user_id": user_id,
    }
    user = db.session.get(User, user_id)
    if user:
        export_data["profile"] = {
            "username": user.username,
            "name": user.name,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_confirmed": user.is_confirmed,
            "oauth_provider": user.oauth_provider,
        }
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        export_data["settings"] = settings.to_dict()
        settings_data = settings.get_settings()
    else:
        settings_data = {}

    export_data["privacy_controls"] = {
        "service_improvement_opt_in": bool(
            settings_data.get(SERVICE_IMPROVEMENT_SETTING_KEY, False)
        ),
        "personalization_enabled": any(
            bool(settings_data.get(key))
            for key in (
                "personalization_instructions",
                "personalization_profession",
                "personalization_more",
            )
        ),
    }
    chats = UserChatHistory.query.filter_by(user_id=user_id).all()
    export_data["chats"] = [chat.to_dict() for chat in chats]
    feedback = AIResponseFeedback.query.filter_by(user_id=user_id).all()
    export_data["ai_response_feedback"] = [item.to_dict() for item in feedback]
    shares = ChatShare.query.filter_by(user_id=user_id).all()
    export_data["shares"] = [share.to_dict() for share in shares]
    minds = Mind.query.filter_by(user_id=user_id).all()
    export_data["minds"] = [mind.to_dict(viewer_id=user_id) for mind in minds]
    pins = MindPin.query.filter_by(user_id=user_id).all()
    export_data["mind_pins"] = [
        {
            "mind_id": pin.mind_id,
            "created_at": pin.created_at.isoformat() if pin.created_at else None,
        }
        for pin in pins
    ]
    github_installations = GitHubInstallation.query.filter_by(user_id=user_id).all()
    export_data["github_installations"] = [
        installation.to_dict() for installation in github_installations
    ]
    github_tasks = GitHubAgentTask.query.filter_by(user_id=user_id).all()
    export_data["github_agent_tasks"] = [task.to_dict() for task in github_tasks]

    return export_data


def delete_user_data(user_id, delete_account=False):
    from utils.audit_log import AuditEvents, log_audit_event
    from utils.auth import (
        AIResponseFeedback,
        ChatShare,
        GitHubAgentTask,
        GitHubInstallation,
        Mind,
        MindPin,
        User,
        UserChatHistory,
        UserSettings,
        db,
    )

    results = {
        "user_id": user_id,
        "deleted_at": datetime.utcnow().isoformat(),
        "items_deleted": {},
    }

    try:
        github_tasks_deleted = GitHubAgentTask.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["github_agent_tasks"] = github_tasks_deleted
        github_installations_deleted = GitHubInstallation.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["github_installations"] = github_installations_deleted
        shares_deleted = ChatShare.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["chat_shares"] = shares_deleted
        feedback_deleted = AIResponseFeedback.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["ai_response_feedback"] = feedback_deleted
        chats = UserChatHistory.query.filter_by(user_id=user_id).all()
        chat_session_ids = [chat.session_id for chat in chats]
        managed_references = merge_managed_references(
            *(collect_managed_references(chat.get_messages()) for chat in chats)
        )
        chats_deleted = UserChatHistory.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["chats"] = chats_deleted
        owned_mind_ids = [mind.id for mind in Mind.query.filter_by(user_id=user_id).all()]
        pins_deleted = MindPin.query.filter_by(user_id=user_id).delete()
        if owned_mind_ids:
            pins_deleted += MindPin.query.filter(MindPin.mind_id.in_(owned_mind_ids)).delete(
                synchronize_session=False
            )
            UserChatHistory.query.filter(UserChatHistory.mind_id.in_(owned_mind_ids)).update(
                {"mind_id": None},
                synchronize_session=False,
            )
        minds_deleted = Mind.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["minds"] = minds_deleted
        results["items_deleted"]["mind_pins"] = pins_deleted
        settings_deleted = UserSettings.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["settings"] = settings_deleted
        if delete_account:
            user = db.session.get(User, user_id)
            if user:
                db.session.delete(user)
                results["items_deleted"]["account"] = 1
                results["account_deleted"] = True

        db.session.commit()

        files_deleted = 0
        chats_folder = _configured_folder("CHATS_FOLDER", CHATS_FOLDER)
        for session_id in chat_session_ids:
            try:
                safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
                chat_file = chats_folder / f"{safe_id}.json"
                if chat_file.exists():
                    os.remove(chat_file)
                    files_deleted += 1
            except OSError:
                logger.warning("Could not remove a legacy chat file", exc_info=True)
        results["items_deleted"]["chat_files"] = files_deleted
        try:
            referenced_files_deleted = delete_unreferenced_managed_files(managed_references)
        except Exception:
            logger.exception("Could not finish privacy asset cleanup")
            referenced_files_deleted = {"uploads": 0, "generated_images": 0}
        results["items_deleted"]["uploaded_files"] = referenced_files_deleted["uploads"]
        results["items_deleted"]["generated_images"] = referenced_files_deleted["generated_images"]

        log_audit_event(
            AuditEvents.DELETE_USER_DATA,
            {"items_deleted": results["items_deleted"], "account_deleted": delete_account},
            user_id,
        )
        if delete_account:
            log_audit_event(AuditEvents.DELETE_ACCOUNT, {"account_deleted": True}, user_id)

        return results

    except Exception as e:
        db.session.rollback()
        raise e


def anonymize_user_data(user_id):
    from utils.auth import (
        AIResponseFeedback,
        GitHubAgentTask,
        GitHubInstallation,
        User,
        UserChatHistory,
        UserSettings,
        db,
    )

    user = db.session.get(User, user_id)
    if not user:
        return False
    anonymous_id = hashlib.sha256(str(user_id).encode()).hexdigest()[:12]
    user.username = f"deleted_user_{anonymous_id}"
    user.name = "Deleted User"
    user.email = f"{anonymous_id}@deleted.invalid"
    user.password = None
    user.confirmation_token = None
    user.reset_token = None
    user.oauth_id = None
    GitHubAgentTask.query.filter_by(user_id=user_id).delete()
    GitHubInstallation.query.filter_by(user_id=user_id).delete()
    UserSettings.query.filter_by(user_id=user_id).delete()
    AIResponseFeedback.query.filter_by(user_id=user_id).delete()
    chats = UserChatHistory.query.filter_by(user_id=user_id).all()
    managed_references = merge_managed_references(
        *(collect_managed_references(chat.get_messages()) for chat in chats)
    )
    for chat in chats:
        chat.title = "Deleted Chat"
        chat.messages_data = "[]"

    db.session.commit()
    try:
        delete_unreferenced_managed_files(managed_references)
    except Exception:
        logger.exception("Could not finish anonymized-user asset cleanup")
    return True


class PrivacySettings:
    LOG_IP_ADDRESSES = False
    LOG_USER_AGENTS = False
    LOG_EMAIL_ADDRESSES = False
    AUDIT_LOG_RETENTION = 90
    SESSION_LOG_RETENTION = 30
    CHAT_RETENTION = 365
    ANONYMIZE_IPS = True
    HASH_EMAILS_IN_LOGS = True
