import re

from sqlalchemy.exc import IntegrityError

from backend.db.models import ChatShare, UserChatHistory, db
from backend.services.project_resources import SESSION_ID, owned_workspace, resource_error

WORKSPACE_ID = re.compile(r"[a-f0-9]{32}")


def _bound_chat(owner, workspace_id, session_id, *, lock=False):
    query = UserChatHistory.query.filter_by(
        user_id=owner, session_id=session_id
    ).populate_existing()
    if lock:
        query = query.with_for_update()
    chat = query.one_or_none()
    if chat is not None and (chat.workspace_id != workspace_id or chat.source != "web"):
        raise resource_error("workspace_chat_scope_changed", 409)
    if ChatShare.query.filter_by(user_id=owner, session_id=session_id, is_public=True).first():
        raise resource_error("workspace_chat_scope_changed", 409)
    return chat


def verify_project_chat(owner, workspace_id, session_id):
    if not owner:
        raise resource_error("auth_required", 401)
    if not isinstance(workspace_id, str) or WORKSPACE_ID.fullmatch(workspace_id) is None:
        raise resource_error("workspace_not_found", 404)
    if not isinstance(session_id, str) or SESSION_ID.fullmatch(session_id) is None:
        raise resource_error("workspace_chat_scope_changed", 409)
    owned_workspace(owner, workspace_id)
    _bound_chat(owner, workspace_id, session_id)


def bind_project_chat(owner, workspace_id, session_id):
    locked = owned_workspace(owner, workspace_id, lock=True)
    chat = _bound_chat(owner, locked.id, session_id, lock=True)
    if chat is None:
        try:
            with db.session.begin_nested():
                db.session.add(
                    UserChatHistory(
                        user_id=owner, session_id=session_id, workspace_id=locked.id, source="web"
                    )
                )
                db.session.flush()
        except IntegrityError:
            if _bound_chat(owner, locked.id, session_id, lock=True) is None:
                raise
    db.session.commit()
