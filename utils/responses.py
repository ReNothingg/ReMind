import logging
from logging.config import dictConfig
from typing import Optional, Union
from flask import g, has_request_context, jsonify

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s.%(funcName)s: %(message)s"
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)
logger = logging.getLogger(__name__)


def _current_request_id() -> Optional[str]:
    if not has_request_context():
        return None
    return getattr(g, "request_id", None)

def make_ok(payload: Optional[Union[dict, list, str]] = None, status: int = 200):
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
    extra: Optional[dict] = None,
):
    err = {"ok": False, "error": {"message": message}}
    request_id = _current_request_id()
    if request_id:
        err["request_id"] = request_id
    if code:
        err["error"]["code"] = code
    if extra:
        err["error"].update(extra)
    return jsonify(err), status
