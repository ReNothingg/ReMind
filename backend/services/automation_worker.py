import json

from celery import shared_task

from backend.errors import ApiError
from backend.observability.logging import logger
from backend.services import automations
from backend.services.chat.generation import generate_chat
from backend.services.chat.streaming import ChatStream


def generate_run(run_id, claimed):
    owner, session_id, prompt, model, web_search = claimed
    result = generate_chat(
        session_id,
        {
            "message": prompt,
            "request_id": f"automation_{run_id}",
            "user_message_id": f"u_{run_id}",
            "assistant_message_id": f"a_{run_id}",
            "webSearch": web_search,
            "_automation": True,
        },
        model,
        db_user_id=owner,
        remote_addr=None,
    )
    if isinstance(result, ChatStream):
        complete = False
        for event in result.events:
            data = json.loads(event.removeprefix("data: ").strip())
            if data.get("delivery_status") == "complete":
                complete = True
        return None if complete else "automation_generation_failed"
    if not isinstance(result, dict) or not result.get("ok", True):
        return "automation_generation_failed"
    return None


@shared_task(
    name="remind.automation.run",
    ignore_result=True,
    soft_time_limit=automations.RUN_TIMEOUT - 45,
    time_limit=automations.RUN_TIMEOUT,
)
def execute_automation(run_id):
    claimed = automations.claim_run(run_id)
    if claimed is None:
        return
    try:
        error = generate_run(run_id, claimed)
    except ApiError as exc:
        error = (
            exc.code
            if exc.code in {"model_access_denied", "mind_external_use_forbidden"}
            else "automation_generation_failed"
        )
    except Exception as exc:
        logger.warning("Automation generation failed (%s)", type(exc).__name__)
        error = "automation_generation_failed"
    automations.finish_run(run_id, error)


@shared_task(name="remind.automation.poll", ignore_result=True)
def poll_automations():
    for run_id in automations.queue_due_tasks():
        execute_automation.apply_async(args=[run_id], expires=60)
