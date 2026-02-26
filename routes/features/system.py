from __future__ import annotations

import os
import time
from datetime import datetime

from flask import Response, current_app, jsonify, request, send_file, send_from_directory
from sqlalchemy import text

from config import BASE_PATH
from routes.api_errors import ApiError, api_error_boundary
from utils.auth import db
from utils.observability import export_prometheus_metrics
from utils.responses import logger, make_error


def register_system_routes(api_bp):
    @api_bp.route("/voice/")
    @api_bp.route("/voice/index.html")
    def voice_index():
        return send_from_directory(str(BASE_PATH / "voice"), "index.html")

    @api_bp.route("/voice/<path:filename>")
    def voice_static(filename):
        return send_from_directory(str(BASE_PATH / "voice"), filename)

    @api_bp.route("/<path:path>")
    def serve_static(path):
        return send_from_directory(current_app.static_folder, path)

    @api_bp.route("/")
    def root_index():
        return send_from_directory(current_app.static_folder, "index.html")

    @api_bp.route("/c/<path:anything>")
    def spa_chat_route(anything):
        return send_from_directory(current_app.static_folder, "index.html")

    @api_bp.route("/openapi.json", methods=["GET"])
    @api_error_boundary("openapi_spec_failed")
    def openapi_spec():
        spec_path = BASE_PATH / "openapi" / "openapi.json"
        if not spec_path.exists():
            raise ApiError("OpenAPI contract not found", status=404, code="not_found")
        return send_file(str(spec_path), mimetype="application/json")

    @api_bp.route("/health", methods=["GET"])
    def health():
        started_at = time.perf_counter()
        checks = {}
        status = "ok"
        http_status = 200

        try:
            db.session.execute(text("SELECT 1"))
            checks["database"] = {"status": "ok"}
        except Exception as exc:
            checks["database"] = {"status": "fail", "reason": "unreachable"}
            logger.error("Health-check database probe failed: %s", exc)
            status = "fail"
            http_status = 503

        storage_checks = {}
        for cfg_key in ("UPLOAD_FOLDER", "CHATS_FOLDER", "CREATE_IMAGE_FOLDER"):
            folder = current_app.config.get(cfg_key)
            writable = bool(folder and os.path.isdir(folder) and os.access(folder, os.W_OK))
            storage_checks[cfg_key.lower()] = {
                "status": "ok" if writable else "fail",
                "path": str(folder),
            }
            if not writable:
                status = "fail"
                http_status = 503
        checks["storage"] = storage_checks

        session_redis = current_app.config.get("SESSION_REDIS")
        if session_redis is not None:
            try:
                session_redis.ping()
                checks["redis"] = {"status": "ok"}
            except Exception as exc:
                checks["redis"] = {"status": "degraded", "reason": "unreachable"}
                logger.warning("Health-check redis probe failed: %s", exc)
                if status == "ok":
                    status = "degraded"

        now_mono = time.perf_counter()
        startup_mono = current_app.config.get("APP_STARTED_MONOTONIC", now_mono)
        include_full = (request.args.get("full", "") or "").lower() in {"1", "true", "yes"}

        payload = {
            "ok": status != "fail",
            "status": status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "uptime_seconds": round(max(0.0, now_mono - startup_mono), 3),
            "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
        }
        if include_full or status != "ok":
            payload["checks"] = checks

        return jsonify(payload), http_status

    @api_bp.route("/metrics", methods=["GET"])
    def metrics():
        try:
            return Response(
                export_prometheus_metrics(),
                mimetype="text/plain; version=0.0.4; charset=utf-8",
            )
        except Exception as exc:
            logger.exception("Failed to export metrics: %s", exc)
            return make_error("Metrics export failed", status=500, code="metrics_export_failed")
