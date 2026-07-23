from __future__ import annotations

import os
import time
from datetime import datetime
from ipaddress import ip_address

from flask import (
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
)
from sqlalchemy import text

from config import (
    BASE_PATH,
    OPERATIONAL_ENDPOINT_ALLOWED_NETWORKS,
    PUBLIC_METRICS_ENABLED,
    PUBLIC_OPENAPI_ENABLED,
)
from routes.api_errors import ApiError, api_error_boundary
from services.model_access import list_accessible_models
from utils.auth import db
from utils.observability import export_prometheus_metrics
from utils.responses import logger, make_error


def _prefer_html_health_page() -> bool:
    format_hint = (request.args.get("format", "") or "").strip().lower()
    if format_hint in {"json", "raw"}:
        return False
    if format_hint in {"html", "page"}:
        return True

    accepts = request.accept_mimetypes
    best = accepts.best_match(["application/json", "text/html"])
    if best != "text/html":
        return False

    return accepts["text/html"] > accepts["application/json"]


def _has_operational_access() -> bool:
    raw_addr = request.remote_addr or ""
    try:
        client_ip = ip_address(raw_addr)
    except ValueError:
        return False

    return any(client_ip in network for network in OPERATIONAL_ENDPOINT_ALLOWED_NETWORKS)


def _operational_not_found():
    return make_error("Not found", status=404, code="not_found")


def _blocked_static_path(path: str) -> bool:
    normalized = (path or "").replace("\\", "/").lower()
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return False
    if any(segment.startswith(".") for segment in segments):
        return True
    return any(segment.endswith((".php", ".phtml", ".phar")) for segment in segments)


def _format_uptime(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _resolve_app_css_url() -> str | None:
    static_folder = current_app.static_folder
    if not static_folder:
        return None

    assets_dir = os.path.join(static_folder, "assets")
    if not os.path.isdir(assets_dir):
        return None

    try:
        candidates = [
            name
            for name in os.listdir(assets_dir)
            if name.startswith("index-") and name.endswith(".css")
        ]
    except OSError:
        return None

    if not candidates:
        return None

    candidates.sort(key=lambda name: os.path.getmtime(os.path.join(assets_dir, name)), reverse=True)
    return f"/assets/{candidates[0]}"


def register_system_routes(api_bp):
    @api_bp.route("/api/models", methods=["GET"])
    def api_models():
        user_id = session.get("user_id")
        try:
            db_user_id = int(user_id) if user_id is not None else None
        except (TypeError, ValueError):
            db_user_id = None
        return jsonify({"models": list_accessible_models(db_user_id)}), 200

    @api_bp.route("/voice/")
    @api_bp.route("/voice/index.html")
    def voice_index():
        return send_from_directory(str(BASE_PATH / "voice"), "index.html")

    @api_bp.route("/voice/<path:filename>")
    def voice_static(filename):
        return send_from_directory(str(BASE_PATH / "voice"), filename)

    @api_bp.route("/<path:path>")
    def serve_static(path):
        if _blocked_static_path(path):
            return _operational_not_found()
        return send_from_directory(current_app.static_folder, path)

    @api_bp.route("/")
    def root_index():
        return send_from_directory(current_app.static_folder, "index.html")

    @api_bp.route("/minds")
    @api_bp.route("/minds/<path:anything>")
    def spa_minds_route(anything=None):
        return send_from_directory(current_app.static_folder, "index.html")

    @api_bp.route("/admin")
    @api_bp.route("/admin/<path:anything>")
    def spa_admin_route(anything=None):
        return send_from_directory(current_app.static_folder, "index.html")

    @api_bp.route("/editor")
    @api_bp.route("/editor/<path:anything>")
    def legacy_editor_route(anything=None):
        suffix = f"/{anything}" if anything else ""
        return redirect(f"/minds/editor{suffix}", code=308)

    @api_bp.route("/c/<path:anything>")
    def spa_chat_route(anything):
        return send_from_directory(current_app.static_folder, "index.html")

    @api_bp.route("/openapi.json", methods=["GET"])
    @api_error_boundary("openapi_spec_failed")
    def openapi_spec():
        if not PUBLIC_OPENAPI_ENABLED and not _has_operational_access():
            return _operational_not_found()
        spec_path = BASE_PATH / "openapi" / "openapi.json"
        if not spec_path.exists():
            raise ApiError("OpenAPI contract not found", status=404, code="not_found")
        return send_file(str(spec_path), mimetype="application/json")

    @api_bp.route("/health/index.css", methods=["GET"])
    def health_stylesheet():
        css_path = BASE_PATH / "src" / "styles" / "health" / "index.css"
        if not css_path.exists():
            return make_error("Health stylesheet not found", status=404, code="not_found")
        return send_file(str(css_path), mimetype="text/css")

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
        has_operational_access = _has_operational_access()
        include_full = has_operational_access and (
            (request.args.get("full", "") or "").lower() in {"1", "true", "yes"}
        )

        detailed_payload = {
            "ok": status != "fail",
            "status": status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "uptime_seconds": round(max(0.0, now_mono - startup_mono), 3),
            "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
        }
        if include_full or status != "ok":
            detailed_payload["checks"] = checks

        if not has_operational_access:
            return jsonify({"ok": status != "fail"}), http_status

        if _prefer_html_health_page():
            component_checks = []

            database_check = checks.get("database")
            if isinstance(database_check, dict):
                component_checks.append(
                    {
                        "name": "Database",
                        "status": database_check.get("status", "unknown"),
                        "reason": database_check.get("reason"),
                        "path": None,
                    }
                )

            redis_check = checks.get("redis")
            if isinstance(redis_check, dict):
                component_checks.append(
                    {
                        "name": "Redis",
                        "status": redis_check.get("status", "unknown"),
                        "reason": redis_check.get("reason"),
                        "path": None,
                    }
                )

            storage_details = checks.get("storage", {})
            if isinstance(storage_details, dict):
                for key, item in storage_details.items():
                    item_data = item if isinstance(item, dict) else {}
                    component_checks.append(
                        {
                            "name": key.replace("_", " ").title(),
                            "status": item_data.get("status", "unknown"),
                            "reason": item_data.get("reason"),
                            "path": item_data.get("path"),
                        }
                    )

            return (
                render_template(
                    "health.html",
                    payload=detailed_payload,
                    status=status,
                    http_status=http_status,
                    uptime_human=_format_uptime(detailed_payload["uptime_seconds"]),
                    component_checks=component_checks,
                    raw_json_url="/health?format=json&full=true",
                    shared_stylesheet_url=_resolve_app_css_url(),
                ),
                http_status,
            )
        return jsonify(detailed_payload), http_status

    @api_bp.route("/metrics", methods=["GET"])
    def metrics():
        if not PUBLIC_METRICS_ENABLED and not _has_operational_access():
            return _operational_not_found()
        try:
            return Response(
                export_prometheus_metrics(),
                mimetype="text/plain; version=0.0.4; charset=utf-8",
            )
        except Exception as exc:
            logger.exception("Failed to export metrics: %s", exc)
            return make_error("Metrics export failed", status=500, code="metrics_export_failed")

    @api_bp.route("/.well-known/security.txt", methods=["GET"])
    def security_txt():
        body = "\n".join(
            [
                "Contact: mailto:synvexai@gmail.com",
                "Policy: https://synvexai.com/policies/privacy-policy/",
                "Preferred-Languages: en, ru",
                "Canonical: https://chat.synvexai.com/.well-known/security.txt",
                "",
            ]
        )
        return Response(body, mimetype="text/plain; charset=utf-8")

    @api_bp.route("/.well-known/change-password", methods=["GET"])
    def well_known_change_password():
        return redirect("/forgot_password", code=302)

    @api_bp.route("/.well-known/http-opportunistic", methods=["GET"])
    def well_known_http_opportunistic():
        # RFC 8164 is obsolete and this service does not opt into opportunistic
        # HTTP. Return an explicit non-discovery response instead of involving
        # the SPA/static-file fallback.
        response, status = _operational_not_found()
        response.headers["Cache-Control"] = "no-store"
        return response, status
