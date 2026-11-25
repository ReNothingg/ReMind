from unicodedata import normalize

from sqlalchemy import and_

from backend.db.models import ChatShare, UserChatHistory, db
from backend.services.chat.context_compaction import historical_messages
from backend.services.chat.conversation import materialize_conversation_history

RESULT_LIMIT = 40
SCAN_LIMIT = 24_000_000


def _normalize(value):
    return " ".join(normalize("NFKC", value).split())


def _find_preview(chat, term):
    messages = [
        item
        for item in materialize_conversation_history(chat.get_messages())
        if item.get("role") in {"user", "model"}
    ]
    for item in reversed(historical_messages(messages)):
        visible = _normalize(item["text"])
        index = visible.casefold().find(term)
        if index >= 0:
            return visible[max(0, index - 48) : index + 108]
    return None


def search_sidebar_sessions(owner, query, source):
    term = _normalize(query).casefold()
    if not term:
        return {"sessions": [], "partial": False}
    rows = (
        db.session.query(UserChatHistory, ChatShare.is_public, ChatShare.public_id)
        .outerjoin(
            ChatShare,
            and_(
                ChatShare.user_id == owner,
                ChatShare.session_id == UserChatHistory.session_id,
            ),
        )
        .filter(UserChatHistory.user_id == owner)
    )
    if source == "web":
        rows = rows.filter(UserChatHistory.source == "web")
    elif source == "telegram":
        rows = rows.filter(UserChatHistory.source.like(r"telegram\_%", escape="\\"))
    rows = rows.order_by(UserChatHistory.updated_at.desc(), UserChatHistory.id.desc())
    matches = []
    scanned = 0
    for chat, public, public_id in rows.yield_per(16):
        scored_title = term in _normalize(chat.title or "").casefold()
        if not scored_title:
            size = len(chat.messages_data or "")
            if scanned + size > SCAN_LIMIT:
                return {"sessions": matches, "partial": True}
            scanned += size
        preview = "" if scored_title else _find_preview(chat, term)
        if preview is None:
            continue
        when = chat.updated_at or chat.created_at
        matches.append(
            {
                "session_id": chat.session_id,
                "workspace_id": chat.workspace_id,
                "title": chat.title or "",
                "last_updated": when.timestamp() if when else 0,
                "last_message": preview,
                "source": chat.source or "web",
                "is_public": bool(public),
                "public_id": public_id,
            }
        )
        if len(matches) == RESULT_LIMIT:
            return {"sessions": matches, "partial": True}
    return {"sessions": matches, "partial": False}
