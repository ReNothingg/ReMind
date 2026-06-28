from __future__ import annotations

from flask import request

from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from utils.feedback import save_ai_response_feedback
from utils.responses import make_ok


def register_feedback_routes(api_bp):
    @api_bp.route("/api/feedback/ai-response", methods=["POST"])
    @api_error_boundary("ai_response_feedback_failed")
    def ai_response_feedback():
        user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise ApiError("Invalid JSON payload", status=400, code="invalid_json")

        feedback = save_ai_response_feedback(user_id, payload)
        return make_ok(
            {
                "feedback": {
                    "rating": feedback.rating,
                    "service_improvement_opt_in": bool(feedback.service_improvement_opt_in),
                }
            }
        )
