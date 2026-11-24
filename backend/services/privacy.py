import hashlib
import os
from datetime import datetime
from pathlib import Path

from flask import current_app, has_app_context

from backend.config import CHATS_FOLDER, CREATE_IMAGE_FOLDER, UPLOAD_FOLDER
from backend.db.models import AgentProviderKey, AgentSkill, WorkspacePatchProposal
from backend.responses import logger
from backend.services import chatgpt_account, workspaces
from backend.services.attachment_lifecycle import (
    collect_managed_references,
    delete_unreferenced_managed_files,
    merge_managed_references,
)
from backend.services.telegram import agent as telegram_agent

SERVICE_IMPROVEMENT_SETTING_KEY = "service_improvement_opt_in"


def anonymize_ip(ip_address):
    if not ip_address:
        return None

    if ":" in ip_address:
        parts = ip_address.split(":")
        if len(parts) > 2:
            return ":".join(parts[:3]) + "::0"
    else:
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
    from backend.auth.accounts import is_telegram_placeholder_email
    from backend.db.models import (
        AIResponseFeedback,
        AutomationProposal,
        AutomationTask,
        ChatShare,
        GitHubAgentTask,
        GitHubInstallation,
        Mind,
        MindPin,
        ReMindWorkspace,
        User,
        UserChatHistory,
        UserSettings,
        db,
    )
    from backend.services.agent_plugins import catalog
    from backend.services.automations import serialize_run, serialize_task, task_runs
    from backend.services.project_resources import workspace_document

    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "user_id": user_id,
    }
    user = db.session.get(User, user_id)
    if user:
        export_data["profile"] = {
            "username": user.username,
            "name": user.name,
            "email": None if is_telegram_placeholder_email(user) else user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_confirmed": user.is_confirmed,
            "oauth_provider": user.oauth_provider,
            "auth_methods": user.to_dict().get("auth_methods", []),
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
    export_data["projects"] = [
        {**workspace_document(row), "created_at": row.created_at.isoformat()}
        for row in ReMindWorkspace.query.filter_by(user_id=user_id).all()
    ]
    export_data["automations"] = [
        {**serialize_task(task), "runs": [serialize_run(run) for run in task_runs(task.id, 100)]}
        for task in AutomationTask.query.filter_by(user_id=user_id).all()
    ]
    export_data["automation_proposals"] = [
        {
            "id": row.id,
            "session_id": row.session_id,
            "operation": row.operation,
            "task_id": row.task_id,
            "changes": row.changes,
            "expires_at": row.expires_at.isoformat(),
            "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        }
        for row in AutomationProposal.query.filter_by(user_id=user_id).all()
    ]
    export_data["agent_plugins"] = catalog(user_id)
    export_data["workspace_patch_proposals"] = [
        {
            "id": row.id, "workspace_id": row.workspace_id, "patch": row.patch,
            "changes": row.changes, "expires_at": row.expires_at.isoformat(),
            "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        }
        for row in WorkspacePatchProposal.query.filter_by(user_id=user_id)
    ]
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
    from backend.db.models import (
        AgentPlugin,
        AIResponseFeedback,
        AppleAuthChallenge,
        AuthIdentity,
        AutomationProposal,
        AutomationTask,
        ChatShare,
        GitHubAgentTask,
        GitHubInstallation,
        Mind,
        MindPin,
        ReMindWorkspace,
        User,
        UserChatHistory,
        UserSettings,
        db,
    )
    from backend.security.audit_log import AuditEvents, log_audit_event
    from backend.services.chat.context_compaction import delete_owner_checkpoints
    from backend.services.chat.provider_replay import delete_owner_replays
    from backend.services.project_resources import delete_owner_files, remove_uploads

    results = {
        "user_id": user_id,
        "deleted_at": datetime.utcnow().isoformat(),
        "items_deleted": {},
    }

    try:
        github_tasks_deleted = GitHubAgentTask.query.filter_by(user_id=user_id).delete()
        registration = chatgpt_account.remove_registration(user_id)
        workspace_removal = workspaces.release(user_id)
        telegram_agent.forget(user_id)
        results["items_deleted"]["agent_provider_keys"] = AgentProviderKey.query.filter_by(
            user_id=user_id
        ).delete()
        results["items_deleted"]["chatgpt_connections"] = int(registration is not None)
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
        delete_owner_checkpoints(user_id)
        delete_owner_replays(user_id)
        results["items_deleted"]["workspace_patch_proposals"] = WorkspacePatchProposal.query.filter_by(user_id=user_id).delete()
        chats_deleted = UserChatHistory.query.filter_by(user_id=user_id).delete()
        results["items_deleted"]["chats"] = chats_deleted
        results["items_deleted"]["automations"] = AutomationTask.query.filter_by(
            user_id=user_id
        ).delete()
        results["items_deleted"]["automation_proposals"] = AutomationProposal.query.filter_by(
            user_id=user_id
        ).delete()
        results["items_deleted"]["agent_plugins"] = AgentPlugin.query.filter_by(
            user_id=user_id
        ).delete()
        results["items_deleted"]["agent_skills"] = AgentSkill.query.filter_by(user_id=user_id).delete()
        project_uploads = delete_owner_files(user_id)
        results["items_deleted"]["project_files"] = len(project_uploads)
        results["items_deleted"]["projects"] = ReMindWorkspace.query.filter_by(
            user_id=user_id
        ).delete()
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
            apple_challenges_deleted = AppleAuthChallenge.query.filter_by(
                link_user_id=user_id
            ).delete()
            results["items_deleted"]["apple_auth_challenges"] = apple_challenges_deleted
            auth_identities_deleted = AuthIdentity.query.filter_by(user_id=user_id).delete()
            results["items_deleted"]["auth_identities"] = auth_identities_deleted
            user = db.session.get(User, user_id)
            if user:
                db.session.delete(user)
                results["items_deleted"]["account"] = 1
                results["account_deleted"] = True

        db.session.commit()
        remove_uploads(project_uploads)
        workspaces.notify_removal(workspace_removal)
        if registration is not None:
            results["chatgpt_session_revoked"] = chatgpt_account.revoke_removed(registration)

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
    from backend.db.models import (
        AgentPlugin,
        AIResponseFeedback,
        AppleAuthChallenge,
        AuthIdentity,
        AutomationProposal,
        AutomationTask,
        GitHubAgentTask,
        GitHubInstallation,
        ReMindWorkspace,
        User,
        UserChatHistory,
        UserSettings,
        db,
    )
    from backend.services.chat.context_compaction import delete_owner_checkpoints
    from backend.services.chat.provider_replay import delete_owner_replays
    from backend.services.project_resources import delete_owner_files, remove_uploads

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
    user.oauth_provider = None
    AppleAuthChallenge.query.filter_by(link_user_id=user_id).delete()
    AuthIdentity.query.filter_by(user_id=user_id).delete()
    GitHubAgentTask.query.filter_by(user_id=user_id).delete()
    GitHubInstallation.query.filter_by(user_id=user_id).delete()
    registration = chatgpt_account.remove_registration(user_id)
    workspace_removal = workspaces.release(user_id)
    telegram_agent.forget(user_id)
    AgentProviderKey.query.filter_by(user_id=user_id).delete()
    UserSettings.query.filter_by(user_id=user_id).delete()
    AIResponseFeedback.query.filter_by(user_id=user_id).delete()
    chats = UserChatHistory.query.filter_by(user_id=user_id).all()
    managed_references = merge_managed_references(
        *(collect_managed_references(chat.get_messages()) for chat in chats)
    )
    for chat in chats:
        chat.title = "Deleted Chat"
        chat.messages_data = "[]"
        chat.workspace_id = None
    delete_owner_checkpoints(user_id)
    delete_owner_replays(user_id)
    WorkspacePatchProposal.query.filter_by(user_id=user_id).delete()
    db.session.flush()
    AutomationTask.query.filter_by(user_id=user_id).delete()
    AutomationProposal.query.filter_by(user_id=user_id).delete()
    AgentPlugin.query.filter_by(user_id=user_id).delete()
    AgentSkill.query.filter_by(user_id=user_id).delete()
    project_uploads = delete_owner_files(user_id)
    ReMindWorkspace.query.filter_by(user_id=user_id).delete()

    db.session.commit()
    remove_uploads(project_uploads)
    workspaces.notify_removal(workspace_removal)
    chatgpt_account.revoke_removed(registration)
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
