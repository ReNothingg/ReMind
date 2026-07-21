import logging
from typing import Any, Optional, Union

from flask import g, has_request_context, jsonify

# Keep response and API-boundary logs inside the application's filtered logger
# hierarchy. Configuring the process-wide root logger from this utility module
# would let these records bypass the PII filter installed by setup_logging().
logger = logging.getLogger("remind.responses")


def _current_request_id() -> Optional[str]:
    if not has_request_context():
        return None
    return getattr(g, "request_id", None)


def make_ok(payload: Optional[Union[dict[str, Any], list[Any], str]] = None, status: int = 200):
    if payload is None:
        payload = {}
    if isinstance(payload, dict):
        body = {"ok": True, **payload}
    else:
        body = {"ok": True, "data": payload}
    request_id = _current_request_id()
    if request_id and "request_id" not in body:
        body["request_id"] = request_id
    return jsonify(body), status


def make_error(
    message: str,
    status: int = 400,
    code: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
):
    err: dict[str, Any] = {"ok": False, "error": {"message": message}}
    request_id = _current_request_id()
    if request_id:
        err["request_id"] = request_id
    if code:
        err["error"]["code"] = code
    if extra:
        err["error"].update(extra)
    return jsonify(err), status
