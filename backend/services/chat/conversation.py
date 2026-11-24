import hashlib
import json
import re
import time
import uuid
from typing import Any

from backend.config import CHAT_MAX_VARIANTS_PER_TURN
from backend.services.context_usage import normalize_context_usage

MAX_CHAT_REFERENCES = 3
CHAT_REFERENCE_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
CHAT_REFERENCE_MESSAGE = re.compile(r"[A-Za-z0-9_-]{1,120}")
CHAT_REFERENCE_DIGEST = re.compile(r"[a-f0-9]{64}")
CHAT_REFERENCE_WORKSPACE = re.compile(r"[a-f0-9]{32}")


def normalize_chat_references(value):
    if not isinstance(value, list):
        return []
    references = []
    seen = set()
    for row in value[:MAX_CHAT_REFERENCES]:
        if not isinstance(row, dict):
            continue
        session_id = row.get("session_id")
        message_id = row.get("message_id")
        digest = row.get("digest")
        title = row.get("title")
        scopes = (row.get("workspace_id"), row.get("target_workspace_id"))
        if (
            not isinstance(session_id, str)
            or not CHAT_REFERENCE_ID.fullmatch(session_id)
            or session_id in seen
            or not isinstance(message_id, str)
            or not CHAT_REFERENCE_MESSAGE.fullmatch(message_id)
            or not isinstance(digest, str)
            or not CHAT_REFERENCE_DIGEST.fullmatch(digest)
            or not isinstance(title, str)
            or any(
                scope is not None and (
                    not isinstance(scope, str) or not CHAT_REFERENCE_WORKSPACE.fullmatch(scope)
                )
                for scope in scopes
            )
        ):
            continue
        seen.add(session_id)
        references.append({
            "session_id": session_id,
            "message_id": message_id,
            "digest": digest,
            "title": title[:200],
            "workspace_id": scopes[0],
            "target_workspace_id": scopes[1],
        })
    return references


def _new_message_id() -> str:
    return f"m_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def normalize_message(msg: Any) -> dict:
    try:
        if not isinstance(msg, dict):
            return {
                "id": _new_message_id(),
                "role": "user",
                "parts": [{"text": str(msg)}],
                "timestamp": int(time.time()),
            }

        role = msg.get("role", "user")
        parts = msg.get("parts") or (
            [{"text": msg.get("text")}] if msg.get("text") else [{"text": ""}]
        )
        normalized = {
            "id": msg.get("id") or _new_message_id(),
            "role": role,
            "parts": parts,
            "timestamp": msg.get("timestamp") or int(time.time()),
        }
        if isinstance(msg.get("model_id"), str):
            normalized["model_id"] = msg["model_id"][:100]
        if usage := normalize_context_usage(msg.get("context_usage")):
            normalized["context_usage"] = usage
        if isinstance(msg.get("selected_tools"), list):
            from backend.services.tools.composer_tools import TOOL_IDS

            normalized["selected_tools"] = [
                tool for tool in msg["selected_tools"] if isinstance(tool, str) and tool in TOOL_IDS
            ]
        if role == "user" and isinstance(msg.get("composer_content"), str):
            normalized["composer_content"] = msg["composer_content"][:34048]
        if role == "user" and (references := normalize_chat_references(msg.get("chat_references"))):
            normalized["chat_references"] = references
        sources = msg.get("sources")
        if isinstance(sources, list) and sources:
            normalized["sources"] = sources
        github_tool = msg.get("github_tool")
        if isinstance(github_tool, dict) and github_tool:
            normalized["github_tool"] = github_tool
        canvas_textdoc = msg.get("canvas_textdoc") or msg.get("canvasTextdoc")
        if isinstance(canvas_textdoc, dict) and canvas_textdoc:
            normalized["canvas_textdoc"] = canvas_textdoc
        canvas_updates = msg.get("canvas_updates") or msg.get("canvasUpdates")
        if isinstance(canvas_updates, list) and canvas_updates:
            normalized["canvas_updates"] = canvas_updates
        request_id = msg.get("request_id")
        if isinstance(request_id, str) and request_id:
            normalized["request_id"] = request_id[:100]
        delivery_status = msg.get("delivery_status")
        if delivery_status in {"complete", "interrupted"}:
            normalized["delivery_status"] = delivery_status
        parent_id = msg.get("parent_id")
        if parent_id is None or isinstance(parent_id, str):
            normalized["parent_id"] = parent_id
        normalized["is_active"] = bool(msg.get("is_active", True))
        return normalized
    except Exception:
        return {
            "id": _new_message_id(),
            "role": "user",
            "parts": [{"text": ""}],
            "timestamp": int(time.time()),
        }


def ensure_conversation_graph(messages: list[Any]) -> list[dict]:
    raw_messages = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        candidate = dict(message)
        if not candidate.get("id"):
            fingerprint = hashlib.sha256(
                f"{index}:{_message_signature(candidate)}".encode("utf-8")
            ).hexdigest()[:20]
            candidate["id"] = f"legacy_{fingerprint}"
        raw_messages.append(candidate)
    graph_already_present = any("parent_id" in message for message in raw_messages)
    normalized = [normalize_message(message) for message in raw_messages]
    if not normalized:
        return []

    if graph_already_present:
        valid_ids = {message["id"] for message in normalized}
        for message in normalized:
            parent_id = message.get("parent_id")
            if parent_id is not None and parent_id not in valid_ids:
                message["parent_id"] = None
        _ensure_single_active_sibling(normalized)
        return normalized

    previous: dict | None = None
    for message in normalized:
        if previous is None:
            message["parent_id"] = None
        elif message.get("role") == previous.get("role"):
            message["parent_id"] = previous.get("parent_id")
            previous["is_active"] = False
        else:
            message["parent_id"] = previous.get("id")
        message["is_active"] = True
        previous = message

    _ensure_single_active_sibling(normalized)
    return normalized


def _group_siblings(messages: list[dict]) -> dict[str | None, list[dict]]:
    sibling_groups: dict[str | None, list[dict]] = {}
    for message in messages:
        sibling_groups.setdefault(message.get("parent_id"), []).append(message)
    return sibling_groups


def _ensure_single_active_sibling(messages: list[dict]) -> None:
    for siblings in _group_siblings(messages).values():
        active = [message for message in siblings if message.get("is_active")]
        selected = active[-1] if active else siblings[-1]
        for message in siblings:
            message["is_active"] = message is selected


def _variant_payload(message: dict) -> dict:
    payload = {
        key: value for key, value in message.items() if key not in {"parent_id", "is_active"}
    }
    payload["variant_id"] = message.get("id")
    return payload


def materialize_conversation_history(messages: list[Any]) -> list[dict]:
    graph = ensure_conversation_graph(messages)
    if not graph:
        return []

    sibling_groups = _group_siblings(graph)

    history: list[dict] = []
    parent_id: str | None = None
    visited: set[str] = set()
    while parent_id in sibling_groups:
        siblings = sibling_groups[parent_id]
        current_index = next(
            (
                index
                for index in range(len(siblings) - 1, -1, -1)
                if siblings[index].get("is_active")
            ),
            len(siblings) - 1,
        )
        selected = siblings[current_index]
        message_id = str(selected.get("id") or "")
        if not message_id or message_id in visited:
            break
        visited.add(message_id)
        materialized = dict(selected)
        if len(siblings) > 1:
            materialized["variants"] = [_variant_payload(sibling) for sibling in siblings]
            materialized["current_variant_index"] = current_index
        history.append(materialized)
        parent_id = message_id
    return history


def conversation_context_for_operation(
    messages: list[Any], operation: str, target_message_id: str | None
) -> tuple[list[dict], str | None]:
    path = materialize_conversation_history(messages)
    if operation == "send":
        return [normalize_message(message) for message in path], path[-1]["id"] if path else None

    target_index = next(
        (index for index, message in enumerate(path) if message.get("id") == target_message_id),
        -1,
    )
    if target_index < 0:
        raise ValueError("target_message_not_found")

    target = path[target_index]
    if operation == "regenerate":
        if target.get("role") != "model" or target_index == 0:
            raise ValueError("invalid_regenerate_target")
        user_message = path[target_index - 1]
        if user_message.get("role") != "user":
            raise ValueError("invalid_regenerate_target")
        return [normalize_message(message) for message in path[: target_index - 1]], user_message[
            "id"
        ]

    if operation == "edit":
        if target.get("role") != "user":
            raise ValueError("invalid_edit_target")
        return [normalize_message(message) for message in path[:target_index]], target.get(
            "parent_id"
        )

    raise ValueError("invalid_chat_operation")


def _message_signature(msg: dict) -> str:
    try:
        role = str(msg.get("role") or "").lower()
        parts = msg.get("parts") or []
        pieces = []

        for part in parts:
            if isinstance(part, dict):
                if "text" in part and part["text"] is not None:
                    pieces.append(str(part["text"]))
                elif "url_path" in part:
                    pieces.append(str(part.get("url_path")))
                else:
                    pieces.append(json.dumps(part, sort_keys=True, ensure_ascii=False))
            else:
                pieces.append(str(part))

        body = "||".join(pieces)
        return f"{role}::{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
    except Exception:
        return f"{(msg.get('role') or 'x')}::err"


def collect_new_messages(
    existing_messages: list[dict], incoming_messages: list[dict]
) -> list[dict]:
    existing_ids = {message.get("id") for message in existing_messages}
    recent_signatures = {
        _message_signature(message)
        for message in existing_messages[-10:]
        if isinstance(message, dict)
    }
    fresh_messages: list[dict] = []

    for message in incoming_messages:
        message_id = message.get("id")
        if message_id in existing_ids:
            continue

        signature = _message_signature(message)
        if signature in recent_signatures:
            continue

        existing_ids.add(message_id)
        recent_signatures.add(signature)
        fresh_messages.append(message)

    return fresh_messages


def _deactivate_siblings(graph: list[dict], parent_id: str | None) -> None:
    for message in graph:
        if message.get("parent_id") == parent_id:
            message["is_active"] = False


def _activate_ancestry(graph: list[dict], message_id: str | None) -> None:
    if message_id is None:
        return
    by_id = {message.get("id"): message for message in graph}
    sibling_groups = _group_siblings(graph)
    current = by_id.get(message_id)
    visited: set[str] = set()
    while current and current.get("id") not in visited:
        current_id = str(current.get("id"))
        visited.add(current_id)
        parent_id = current.get("parent_id")
        for sibling in sibling_groups[parent_id]:
            sibling["is_active"] = sibling is current
        current = by_id.get(parent_id)


def apply_chat_operation(
    messages: list[Any],
    *,
    operation: str,
    target_message_id: str | None,
    parent_message_id: str | None,
    user_message: dict | None,
    model_message: dict,
) -> list[dict]:
    graph = ensure_conversation_graph(messages)
    request_id = model_message.get("request_id")
    if request_id and any(message.get("request_id") == request_id for message in graph):
        return graph

    by_id = {message.get("id"): message for message in graph}
    model_node = normalize_message(model_message)
    user_node = normalize_message(user_message) if user_message else None
    incoming_ids = [model_node.get("id")]
    if user_node:
        incoming_ids.append(user_node.get("id"))
    if len(set(incoming_ids)) != len(incoming_ids) or any(
        message_id in by_id for message_id in incoming_ids
    ):
        raise ValueError("message_id_conflict")

    if operation == "send":
        parent_id = parent_message_id if parent_message_id in by_id else None
        if parent_id is None:
            active_path = materialize_conversation_history(graph)
            parent_id = active_path[-1]["id"] if active_path else None
        _activate_ancestry(graph, parent_id)
        if not user_node:
            raise ValueError("missing_user_message")
        user_node["parent_id"] = parent_id
        user_node["is_active"] = True
        _deactivate_siblings(graph, parent_id)
        graph.append(user_node)
        model_node["parent_id"] = user_node["id"]
        model_node["is_active"] = True
        graph.append(model_node)
        return graph

    target = by_id.get(target_message_id)
    if not target:
        raise ValueError("target_message_not_found")

    if operation == "regenerate":
        if target.get("role") != "model":
            raise ValueError("invalid_regenerate_target")
        parent_id = target.get("parent_id")
        if sum(1 for message in graph if message.get("parent_id") == parent_id) >= (
            CHAT_MAX_VARIANTS_PER_TURN
        ):
            raise ValueError("chat_variant_limit_reached")
        _activate_ancestry(graph, parent_id)
        _deactivate_siblings(graph, parent_id)
        model_node["parent_id"] = parent_id
        model_node["is_active"] = True
        graph.append(model_node)
        return graph

    if operation == "edit":
        if target.get("role") != "user" or not user_node:
            raise ValueError("invalid_edit_target")
        parent_id = target.get("parent_id")
        if sum(1 for message in graph if message.get("parent_id") == parent_id) >= (
            CHAT_MAX_VARIANTS_PER_TURN
        ):
            raise ValueError("chat_variant_limit_reached")
        _activate_ancestry(graph, parent_id)
        _deactivate_siblings(graph, parent_id)
        user_node["parent_id"] = parent_id
        user_node["is_active"] = True
        graph.append(user_node)
        model_node["parent_id"] = user_node["id"]
        model_node["is_active"] = True
        graph.append(model_node)
        return graph

    raise ValueError("invalid_chat_operation")


def select_variant_in_graph(messages: list[Any], message_id: str) -> list[dict]:
    graph = ensure_conversation_graph(messages)
    target = next((message for message in graph if message.get("id") == message_id), None)
    if not target:
        raise ValueError("target_message_not_found")
    _activate_ancestry(graph, message_id)
    return graph
