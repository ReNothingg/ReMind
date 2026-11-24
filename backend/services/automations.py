from datetime import timedelta
from uuid import uuid4

from backend.auth.accounts import get_account_restriction
from backend.db.models import (
    AutomationProposal,
    AutomationRun,
    AutomationTask,
    ReMindWorkspace,
    User,
    UserChatHistory,
    db,
)
from backend.errors import ApiError
from backend.services.automation_timing import (
    first_occurrence,
    iso_utc,
    normalize_timing,
    resolve_occurrence,
    utc_now,
)

ACTIVE_STATUSES = ("queued", "running")
MAX_TASKS = 32
MAX_RECEIPTS_PER_TASK = 100
RUN_TIMEOUT = 900
TASK_FIELDS = {
    "title",
    "prompt",
    "model",
    "timing",
    "workspace_id",
    "target_session_id",
    "web_search",
    "enabled",
}


def automation_error(code, status=400):
    return ApiError(code, status=status, code=code)


def get_task(owner, task_id, *, lock=False):
    query = AutomationTask.query.filter_by(user_id=owner, id=task_id)
    task = (query.with_for_update() if lock else query).one_or_none()
    if task is None:
        raise automation_error("automation_not_found", 404)
    return task


def serialize_run(run):
    return {
        "id": run.id,
        "status": run.status,
        "session_id": run.session_id,
        "occurrence_at": iso_utc(run.occurrence_at),
        "queued_at": iso_utc(run.queued_at),
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
        "error": run.error,
    }


def task_runs(task_id, limit=20):
    return (
        AutomationRun.query.filter_by(task_id=task_id)
        .order_by(AutomationRun.queued_at.desc(), AutomationRun.id)
        .limit(limit)
        .all()
    )


def serialize_task(task):
    latest = task_runs(task.id, 1)
    return {
        "id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "model": task.model,
        "workspace_id": task.workspace_id,
        "target_session_id": task.target_session_id,
        "web_search": task.web_search,
        "timing": task.timing,
        "enabled": task.enabled,
        "next_run_at": iso_utc(task.next_run_at) if task.enabled else None,
        "created_at": iso_utc(task.created_at),
        "last_run": serialize_run(latest[0]) if latest else None,
    }


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise automation_error("invalid_automation")
    return value.strip()


def _target(owner, workspace_id, session_id):
    if workspace_id is not None and (
        not isinstance(workspace_id, str)
        or ReMindWorkspace.query.filter_by(id=workspace_id, user_id=owner).one_or_none() is None
    ):
        raise automation_error("automation_target_unavailable", 404)
    if session_id is not None and (
        not isinstance(session_id, str)
        or UserChatHistory.query.filter_by(
            session_id=session_id, user_id=owner, source="web"
        ).one_or_none()
        is None
    ):
        raise automation_error("automation_target_unavailable", 404)


def task_configuration(owner, payload, task, *, future_session=None):
    from backend.services.model_access import can_user_access_model

    if not isinstance(payload, dict) or not payload or set(payload) - TASK_FIELDS:
        raise automation_error("invalid_automation")
    title = _text(payload.get("title", task.title), 120)
    prompt = _text(payload.get("prompt", task.prompt), 12000)
    model = _text(payload.get("model", task.model), 200)
    if model == "demo_image" or (model != task.model and not can_user_access_model(model, owner)):
        raise automation_error("model_access_denied", 403)
    workspace_id = payload.get("workspace_id", task.workspace_id)
    session_id = payload.get("target_session_id", task.target_session_id)
    if workspace_id is not None and session_id is not None:
        raise automation_error("invalid_automation")
    if "workspace_id" in payload or "target_session_id" in payload:
        _target(owner, workspace_id, None if session_id == future_session else session_id)
    enabled = payload.get("enabled", task.enabled)
    web_search = payload.get("web_search", task.web_search)
    if type(enabled) is not bool or type(web_search) is not bool:
        raise automation_error("invalid_automation")
    timing = normalize_timing(payload["timing"]) if "timing" in payload else task.timing
    if timing is None:
        raise automation_error("invalid_automation_rule")
    next_run = task.next_run_at
    if timing != task.timing or (enabled and not task.enabled):
        next_run = first_occurrence(timing, utc_now())
    return {
        "title": title,
        "prompt": prompt,
        "model": model,
        "workspace_id": workspace_id,
        "target_session_id": session_id,
        "web_search": web_search,
        "enabled": enabled,
        "timing": timing,
    }, next_run


def require_task_owner(owner, *, lock=False):
    query = User.query.filter_by(id=owner)
    user = (query.with_for_update() if lock else query).one_or_none()
    if user is None or get_account_restriction(user):
        raise automation_error("automation_account_unavailable", 403)


def save_task(owner, payload, task=None, *, commit=True):
    if task is None:
        require_task_owner(owner, lock=True)
        if AutomationTask.query.filter_by(user_id=owner).count() >= MAX_TASKS:
            raise automation_error("automation_task_limit", 409)
        task = AutomationTask(id=uuid4().hex, user_id=owner, web_search=False, enabled=True)
    values, next_run = task_configuration(owner, payload, task)
    enabled = values["enabled"]
    pause = task.enabled and not enabled
    for key, value in values.items():
        setattr(task, key, value)
    task.next_run_at = next_run
    db.session.add(task)
    if pause:
        AutomationRun.query.filter_by(task_id=task.id, status="queued").update(
            {"status": "cancelled", "finished_at": utc_now()}
        )
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return task


def _ongoing(task_id):
    return (
        AutomationRun.query.filter(
            AutomationRun.task_id == task_id, AutomationRun.status.in_(ACTIVE_STATUSES)
        ).first()
        is not None
    )


def _queue(task, occurrence, now):
    run = AutomationRun(
        id=uuid4().hex, task_id=task.id, status="queued", occurrence_at=occurrence, queued_at=now
    )
    db.session.add(run)
    db.session.flush()
    old = (
        db.select(AutomationRun.id)
        .where(AutomationRun.task_id == task.id)
        .order_by(AutomationRun.queued_at.desc(), AutomationRun.id)
        .offset(MAX_RECEIPTS_PER_TASK)
    )
    db.session.execute(
        db.delete(AutomationRun).where(AutomationRun.task_id == task.id, AutomationRun.id.in_(old))
    )
    return run


def run_now(owner, task_id, *, commit=True):
    task = get_task(owner, task_id, lock=True)
    now = utc_now()
    if _ongoing(task_id):
        raise automation_error("automation_already_running", 409)
    if task.last_requested_at and now - task.last_requested_at < timedelta(seconds=30):
        raise automation_error("automation_rate_limited", 429)
    task.last_requested_at = now
    result = serialize_run(_queue(task, now, now))
    if commit:
        db.session.commit()
    return result


def queue_due_tasks(now=None):
    now = now or utc_now()
    db.session.execute(
        db.delete(AutomationProposal).where(
            AutomationProposal.id.in_(
                db.select(AutomationProposal.id)
                .where(AutomationProposal.expires_at <= now)
                .order_by(AutomationProposal.expires_at)
                .limit(100)
            )
        )
    )
    AutomationRun.query.filter(
        AutomationRun.status == "running",
        AutomationRun.started_at < now - timedelta(seconds=RUN_TIMEOUT + 120),
    ).update(
        {"status": "failed", "error": "automation_interrupted", "finished_at": now},
        synchronize_session=False,
    )
    db.session.commit()
    ongoing = (
        db.select(AutomationRun.id)
        .where(
            AutomationRun.task_id == AutomationTask.id, AutomationRun.status.in_(ACTIVE_STATUSES)
        )
        .exists()
    )
    due = (
        AutomationTask.query.filter(
            AutomationTask.enabled.is_(True), AutomationTask.next_run_at <= now, ~ongoing
        )
        .order_by(AutomationTask.next_run_at, AutomationTask.id)
        .limit(8)
        .with_for_update(skip_locked=True)
        .all()
    )
    for task in due:
        if _ongoing(task.id):
            continue
        occurrence, task.next_run_at = resolve_occurrence(task.timing, task.next_run_at, now)
        _queue(task, occurrence, now)
    db.session.commit()
    return [
        run_id
        for (run_id,) in db.session.query(AutomationRun.id)
        .filter_by(status="queued")
        .order_by(AutomationRun.queued_at)
        .limit(12)
        .all()
    ]


def claim_run(run_id):
    reference = db.session.query(AutomationRun.task_id).filter_by(id=run_id).scalar()
    if reference is None:
        return None
    task = AutomationTask.query.filter_by(id=reference).with_for_update().one_or_none()
    run = AutomationRun.query.filter_by(id=run_id, status="queued").with_for_update().one_or_none()
    if task is None or run is None:
        db.session.rollback()
        return None
    now = utc_now()
    user = db.session.get(User, task.user_id)
    if user is None or get_account_restriction(user):
        run.status, run.error, run.finished_at = "failed", "automation_account_unavailable", now
        db.session.commit()
        return None
    destination = task.target_session_id
    if (
        destination is not None
        and UserChatHistory.query.filter_by(
            session_id=destination, user_id=task.user_id, source="web"
        ).one_or_none()
        is None
    ):
        run.status, run.error, run.finished_at = "failed", "automation_target_unavailable", now
        task.enabled = False
        db.session.commit()
        return None
    if destination is None:
        destination = uuid4().hex
        db.session.add(
            UserChatHistory(
                session_id=destination,
                user_id=task.user_id,
                title=task.title,
                workspace_id=task.workspace_id,
            )
        )
    run.status, run.session_id, run.started_at = "running", destination, now
    claimed = (task.user_id, run.session_id, task.prompt, task.model, task.web_search)
    db.session.commit()
    return claimed


def finish_run(run_id, error):
    db.session.rollback()
    AutomationRun.query.filter_by(id=run_id, status="running").update(
        {"status": "failed" if error else "completed", "error": error, "finished_at": utc_now()}
    )
    db.session.commit()
