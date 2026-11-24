from backend.db.models import AutomationTask
from backend.errors import ApiError
from backend.services import automation_proposals, automations
from backend.services.tools.interaction_tools import panel_event
from backend.services.tools.tool_protocol import ModelToolResult

SCHEDULE_TOOLS = ("schedule_create", "schedule_list", "schedule_view", "schedule_edit")


def execute_schedule_tool(owner, context, name, arguments):
    if owner is None or context is None:
        return ModelToolResult({"ok": False, "error": "tool_not_available"})
    try:
        if name == "schedule_list":
            tasks = AutomationTask.query.filter_by(user_id=owner)
            if "active" in arguments:
                active = AutomationTask.enabled.is_(True) & AutomationTask.next_run_at.is_not(None)
                tasks = tasks.filter(active if arguments["active"] else ~active)
            size = arguments.get("limit", 10)
            offset = arguments.get("offset", 0)
            rows = (
                tasks.order_by(AutomationTask.created_at.desc(), AutomationTask.id)
                .offset(offset)
                .limit(size + 1)
                .all()
            )
            items = []
            for row in rows[:size]:
                summary = automations.serialize_task(row)
                summary.pop("prompt")
                items.append(summary)
            return ModelToolResult(
                {
                    "ok": True,
                    "items": items,
                    "next_offset": offset + size if len(rows) > size else None,
                }
            )
        if name == "schedule_view":
            task = automations.get_task(owner, arguments["task_id"])
            return ModelToolResult({"ok": True, "task": automations.serialize_task(task)})
        operation = "create" if name == "schedule_create" else arguments["operation"]
        proposal = automation_proposals.propose(
            owner,
            context["session_id"],
            context["request_id"],
            context["model"],
            operation,
            arguments,
        )
        return ModelToolResult(
            {"ok": True, "awaiting_user": True},
            events=panel_event("automation", {"proposal_id": proposal.id}),
        )
    except ApiError as error:
        return ModelToolResult({"ok": False, "error": error.code})
