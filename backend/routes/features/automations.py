from flask import request

from backend.db.models import AutomationTask, db
from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import RateLimiter, rate_limit
from backend.services import automation_proposals, automations

mutations = RateLimiter(max_requests=30, time_window=60, namespace="automation_settings")
manual_runs = RateLimiter(max_requests=12, time_window=60, namespace="automation_runs")


def _payload():
    if not request.is_json or (request.content_length or 0) > 80000:
        raise automations.automation_error("invalid_automation")
    return request.get_json(silent=True)


def register_automation_routes(bp):
    @bp.get("/api/automations/proposals/<proposal_id>")
    @api_error_boundary("automation_unavailable")
    def get_automation_proposal(proposal_id):
        owner = require_authenticated_user_id()
        return make_ok(
            {
                "proposal": automation_proposals.serialize(
                    automation_proposals.get(owner, proposal_id)
                )
            }
        )

    @bp.post("/api/automations/proposals/<proposal_id>/apply")
    @rate_limit(mutations, "automation_rate_limited")
    @api_error_boundary("automation_unavailable")
    def apply_automation_proposal(proposal_id):
        owner = require_authenticated_user_id()
        if _payload() != {}:
            raise automations.automation_error("invalid_automation")
        return make_ok({"result": automation_proposals.apply(owner, proposal_id)})

    @bp.get("/api/automations")
    @api_error_boundary("automation_unavailable")
    def list_automations():
        owner = require_authenticated_user_id()
        tasks = AutomationTask.query.filter_by(user_id=owner).order_by(
            AutomationTask.created_at.desc()
        )
        return make_ok({"tasks": [automations.serialize_task(task) for task in tasks]})

    @bp.post("/api/automations")
    @rate_limit(mutations, "automation_rate_limited")
    @api_error_boundary("automation_unavailable")
    def create_automation():
        owner = require_authenticated_user_id()
        task = automations.save_task(owner, _payload())
        return make_ok({"task": automations.serialize_task(task)}, 201)

    @bp.patch("/api/automations/<task_id>")
    @rate_limit(mutations, "automation_rate_limited")
    @api_error_boundary("automation_unavailable")
    def update_automation(task_id):
        owner = require_authenticated_user_id()
        task = automations.get_task(owner, task_id, lock=True)
        task = automations.save_task(owner, _payload(), task)
        return make_ok({"task": automations.serialize_task(task)})

    @bp.delete("/api/automations/<task_id>")
    @rate_limit(mutations, "automation_rate_limited")
    @api_error_boundary("automation_unavailable")
    def delete_automation(task_id):
        owner = require_authenticated_user_id()
        task = automations.get_task(owner, task_id, lock=True)
        db.session.delete(task)
        db.session.commit()
        return make_ok({"deleted": True})

    @bp.get("/api/automations/<task_id>/runs")
    @api_error_boundary("automation_unavailable")
    def list_automation_runs(task_id):
        owner = require_authenticated_user_id()
        task = automations.get_task(owner, task_id)
        return make_ok(
            {"runs": [automations.serialize_run(run) for run in automations.task_runs(task.id)]}
        )

    @bp.post("/api/automations/<task_id>/runs")
    @rate_limit(manual_runs, "automation_rate_limited")
    @api_error_boundary("automation_unavailable")
    def start_automation_run(task_id):
        owner = require_authenticated_user_id()
        return make_ok({"run": automations.run_now(owner, task_id)}, 202)
