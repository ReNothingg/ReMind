import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from backend.db.models import AutomationProposal, AutomationTask, UserChatHistory, db
from backend.services import automations
from backend.services.automation_timing import iso_utc, utc_now

VALID_OPERATIONS = {"create", "edit", "pause", "resume", "run", "delete"}
PROPOSAL_LIFETIME = timedelta(days=2)
MAX_PENDING_PROPOSALS = 24


def _task_state(task):
    configuration = {key: getattr(task, key) for key in automations.TASK_FIELDS}
    return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()


def _origin(owner, session_id):
    return UserChatHistory.query.filter_by(
        user_id=owner, session_id=session_id, source="web"
    ).one_or_none()


def _task_changes(source, origin, session_id, default_model):
    changes = {
        key: value
        for key, value in source.items()
        if key in ("title", "prompt", "timing", "web_search")
    }
    if default_model is not None:
        changes["model"] = default_model
    destination = source.get("destination")
    if destination == "current" or (destination is None and default_model is not None):
        changes.update(target_session_id=session_id, workspace_id=None)
    elif destination == "project":
        if origin is None or origin.workspace_id is None:
            raise automations.automation_error("automation_target_unavailable", 404)
        changes.update(target_session_id=None, workspace_id=origin.workspace_id)
    elif destination == "new":
        changes.update(target_session_id=None, workspace_id=None)
    return changes


def propose(owner, session_id, request_id, model, operation, source):
    if operation not in VALID_OPERATIONS:
        raise automations.automation_error("invalid_automation")
    automations.require_task_owner(owner, lock=True)
    now = utc_now()
    proposals = AutomationProposal.query.filter_by(user_id=owner)
    existing = proposals.filter_by(request_id=request_id).one_or_none()
    if existing:
        if existing.session_id != session_id or existing.expires_at <= now:
            raise automations.automation_error("automation_proposal_expired", 410)
        return existing
    if (
        proposals.filter(
            AutomationProposal.expires_at > now, AutomationProposal.applied_at.is_(None)
        ).count()
        >= MAX_PENDING_PROPOSALS
    ):
        raise automations.automation_error("automation_proposal_limit", 409)

    origin = _origin(owner, session_id)
    task = automations.get_task(owner, source["task_id"]) if operation != "create" else None
    changes = _task_changes(source, origin, session_id, model if task is None else None)
    if operation == "create":
        default = AutomationTask(user_id=owner, enabled=True, web_search=False)
        changes, _ = automations.task_configuration(
            owner, changes, default, future_session=session_id if origin is None else None
        )
    elif operation == "edit":
        validated, _ = automations.task_configuration(
            owner, changes, task, future_session=session_id if origin is None else None
        )
        changes = {key: validated[key] for key in changes}
    elif operation in {"pause", "resume"}:
        changes = {"enabled": operation == "resume"}
        automations.task_configuration(owner, changes, task)
    else:
        changes = {}

    proposal = AutomationProposal(
        id=uuid4().hex,
        user_id=owner,
        request_id=request_id,
        session_id=session_id,
        operation=operation,
        task_id=task.id if task else None,
        task_state=_task_state(task) if task else None,
        changes=changes,
        expires_at=now + PROPOSAL_LIFETIME,
    )
    db.session.add(proposal)
    db.session.commit()
    return proposal


def get(owner, proposal_id, *, lock=False):
    query = AutomationProposal.query.filter_by(id=proposal_id, user_id=owner)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise automations.automation_error("automation_proposal_not_found", 404)
    if row.expires_at <= utc_now():
        raise automations.automation_error("automation_proposal_expired", 410)
    if _origin(owner, row.session_id) is None:
        raise automations.automation_error("automation_proposal_not_found", 404)
    return row


def serialize(proposal):
    task = None
    stale = False
    if proposal.task_id and not proposal.applied_at:
        row = AutomationTask.query.filter_by(
            id=proposal.task_id, user_id=proposal.user_id
        ).one_or_none()
        stale = row is None or _task_state(row) != proposal.task_state
        if row is not None:
            task = automations.serialize_task(row)
    return {
        "id": proposal.id,
        "operation": proposal.operation,
        "changes": proposal.changes,
        "task": task,
        "stale": stale,
        "applied_at": iso_utc(proposal.applied_at),
        "result": proposal.result,
    }


def apply(owner, proposal_id):
    proposal = get(owner, proposal_id, lock=True)
    if proposal.applied_at:
        return proposal.result
    automations.require_task_owner(owner)
    operation = proposal.operation
    task = automations.get_task(owner, proposal.task_id, lock=True) if proposal.task_id else None
    if task is not None and _task_state(task) != proposal.task_state:
        raise automations.automation_error("automation_proposal_changed", 409)

    if operation == "run":
        result = {"task_id": task.id, "run": automations.run_now(owner, task.id, commit=False)}
    elif operation == "delete":
        result = {"removed": True}
        db.session.delete(task)
    else:
        updated = automations.save_task(owner, proposal.changes, task, commit=False)
        result = {"task_id": updated.id}
    proposal.applied_at, proposal.result = utc_now(), result
    db.session.commit()
    return result
