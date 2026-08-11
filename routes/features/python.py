from __future__ import annotations

from flask import request

from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from services.python_runner import MAX_CODE_CHARS, execute_python, python_runner_available
from utils.responses import make_ok


def register_python_routes(api_bp):
    @api_bp.route("/api/python/execute", methods=["POST"])
    @api_error_boundary("python_canvas_execution_failed")
    def execute_canvas_python():
        user_id = require_authenticated_user_id()
        if not python_runner_available(user_id):
            raise ApiError(
                "Python runner is unavailable",
                status=503,
                code="python_runner_unavailable",
            )

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ApiError("Invalid Python execution payload", status=400, code="invalid_code")

        code = payload.get("code")
        if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
            raise ApiError("Invalid Python code", status=400, code="invalid_code")

        result = execute_python(
            code,
            user_id=user_id,
            allow_artifacts=False,
            inline_artifacts=True,
        )
        return make_ok(result.output)
