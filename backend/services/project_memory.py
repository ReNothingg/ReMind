import re

from backend.db.models import ChatShare, ReMindWorkspace, UserChatHistory, db
from backend.services.chat.conversation import materialize_conversation_history
from backend.services.project_resources import resource_path, workspace_files
from backend.services.tools.interaction_tools import readable_panel_history

thinking = re.compile(r"<think(?:\s[^>]*)?>.*?</think>", re.I | re.S)


def _is_shared(owner, session):
    return (
        db.select(ChatShare.id)
        .where(
            ChatShare.user_id == owner,
            ChatShare.session_id == session,
            ChatShare.is_public.is_(True),
        )
        .exists()
    )


def project_memory(owner, session_id, *, expected_workspace=None, exclude_sessions=()):
    if not owner or not isinstance(session_id, str) or not session_id:
        return None
    query = (
        db.select(ReMindWorkspace)
        .join(UserChatHistory, UserChatHistory.workspace_id == ReMindWorkspace.id)
        .where(
            ReMindWorkspace.user_id == owner,
            UserChatHistory.user_id == owner,
            UserChatHistory.session_id == session_id,
            UserChatHistory.source == "web",
            ~_is_shared(owner, session_id),
        )
    )
    if expected_workspace is not None:
        query = query.where(ReMindWorkspace.id == expected_workspace)
    row = db.session.execute(query).scalar_one_or_none()
    if row is None:
        return None
    recent = (
        UserChatHistory.query.filter_by(user_id=owner, workspace_id=row.id, source="web")
        .filter(
            UserChatHistory.session_id.not_in((session_id, *exclude_sessions)),
            ~_is_shared(owner, UserChatHistory.session_id),
        )
        .order_by(UserChatHistory.updated_at.desc())
        .limit(5)
        .all()
    )
    history = []
    for chat in recent:
        visible = []
        for message in materialize_conversation_history(chat.get_messages())[-6:]:
            if message.get("role") not in {"user", "model"}:
                continue
            text = "\n".join(
                part["text"]
                for part in message.get("parts", [])
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
            cleaned = readable_panel_history(thinking.sub("", text)).strip()
            if cleaned:
                visible.append({"role": message["role"], "text": cleaned[:1000]})
        if visible:
            history.append({"title": (chat.title or "")[:120], "messages": visible})
    files = []
    for item in workspace_files(row.id):
        if path := resource_path(item.storage_name):
            files.append(
                {
                    "path": str(path),
                    "original_name": item.original_name,
                    "mime_type": item.mime_type,
                    "size": item.size,
                    "workspace_file_id": item.id,
                }
            )
    return {
        "id": row.id,
        "project": row.name,
        "chats": history,
        "instructions": row.instructions or "",
        "files": files,
    }
