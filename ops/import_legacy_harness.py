import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

from flask import Flask

from backend.db.models import AgentWorkspaceSlot, ReMindWorkspace, UserChatHistory, db


class InvalidSnapshot(ValueError):
    pass


def require(valid, reason):
    if not valid:
        raise InvalidSnapshot(reason)


def identifier(value):
    require(isinstance(value, str) and 0 < len(value) <= 4096, "Invalid legacy identifier")
    return value


def digest(*components):
    return hashlib.sha256(json.dumps(components, ensure_ascii=True).encode()).hexdigest()


def event_time(value, fallback=None):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seconds = value / 1000 if value > 100000000000 else value
            return datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None)
        if isinstance(value, str):
            time = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if time.tzinfo is not None:
                time = time.astimezone(timezone.utc)
            return time.replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        pass
    if fallback is not None:
        return fallback
    raise InvalidSnapshot("Invalid legacy creation time")


def snapshot_rows(source):
    total_size = 0
    while line := source.readline(40 * 1024 * 1024 + 1):
        total_size += len(line)
        require(
            total_size <= 256 * 1024 * 1024 and line.endswith(b"\n"),
            "Incomplete or oversized snapshot",
        )
        require(len(line) <= 40 * 1024 * 1024, "Oversized snapshot record")
        row = json.loads(line)
        require(isinstance(row, dict), "Invalid snapshot record")
        yield row


def load_slots(source):
    snapshots = {}
    current = None
    for row in snapshot_rows(source):
        record = row.get("record")
        if record == "slot":
            slot = row.get("slot")
            workspace = row.get("workspace")
            generation = row.get("generation")
            require(
                current is None and type(slot) is int and slot > 0 and slot not in snapshots,
                "Invalid slot header",
            )
            require(
                isinstance(workspace, str) and re.fullmatch(r"[a-f0-9]{32}", workspace),
                "Invalid workspace lease",
            )
            require(type(generation) is int and generation >= 0, "Invalid lease generation")
            current = {
                "slot": slot,
                "workspace": workspace,
                "generation": generation,
                "projects": {},
                "chats": {},
            }
            continue
        require(current is not None, "Snapshot record has no slot")
        if record in {"project", "chat"}:
            record_id = identifier(row.get("key" if record == "project" else "id"))
            records = current["projects" if record == "project" else "chats"]
            require(record_id not in records, "Duplicate legacy record")
            records[record_id] = row
        elif record == "end":
            counts = row.get("counts")
            require(
                isinstance(counts, dict) and counts.get("invalid") == 0,
                "Snapshot contains unreadable sessions",
            )
            require(
                counts.get("projects") == len(current["projects"])
                and counts.get("chats") == len(current["chats"]),
                "Snapshot counts disagree",
            )
            snapshots[current["slot"]] = current
            current = None
        else:
            raise InvalidSnapshot("Unknown legacy snapshot record")
    require(snapshots and current is None, "Snapshot is empty or incomplete")
    return snapshots


def import_project(owner, workspace, legacy_id, row):
    project_id = digest("legacy-harness-project", workspace, legacy_id)[:32]
    existing = db.session.get(ReMindWorkspace, project_id)
    if existing:
        require(existing.user_id == owner, "Imported project owner disagrees with lease")
        return project_id, 0
    name = row.get("name")
    require(isinstance(name, str), "Invalid project title")
    db.session.add(
        ReMindWorkspace(
            id=project_id,
            user_id=owner,
            name=name.strip()[:80] or "Workspace",
            created_at=event_time(row.get("createdAt")),
        )
    )
    return project_id, 1


def conversation(row, chat_hash, created):
    messages = row.get("messages")
    require(isinstance(messages, list) and messages, "Invalid legacy message list")
    graph = []
    latest = created
    for index, item in enumerate(messages):
        require(
            isinstance(item, dict) and item.get("role") in ("user", "model"),
            "Invalid legacy message role",
        )
        text = item.get("text")
        require(isinstance(text, str) and text.strip(), "Invalid legacy message content")
        sent = event_time(item.get("at"), latest)
        latest = max(latest, sent)
        message = {
            "id": digest("legacy-harness-message", chat_hash, index)[:20],
            "parent_id": graph[-1]["id"] if graph else None,
            "role": item["role"],
            "parts": [{"text": text}],
            "is_active": True,
            "timestamp": int(sent.replace(tzinfo=timezone.utc).timestamp()),
        }
        if isinstance(item.get("model"), str):
            message["model_id"] = item["model"][:100]
        graph.append(message)
    return graph, latest


def import_chat(owner, workspace, legacy_id, row, projects):
    chat_hash = digest("legacy-harness-chat", workspace, legacy_id)
    if UserChatHistory.query.filter_by(user_id=owner, external_ref_hash=chat_hash).first():
        return 0
    project = row.get("project")
    require(
        project is None or (isinstance(project, str) and project in projects),
        "Missing legacy chat project",
    )
    created = event_time(row.get("createdAt"))
    messages, updated = conversation(row, chat_hash, created)
    title = row.get("title")
    require(isinstance(title, str), "Invalid legacy chat title")
    if not title.strip():
        title = next(
            (message["parts"][0]["text"] for message in messages if message["role"] == "user"), ""
        )
    title = " ".join(title[:1000].split())[:200] or "Chat"
    db.session.add(
        UserChatHistory(
            user_id=owner,
            session_id=chat_hash[:32],
            workspace_id=projects.get(project),
            title=title,
            source="web",
            external_ref_hash=chat_hash,
            source_context_data='{"migration":"legacy_workspace"}',
            messages_data=json.dumps(messages, ensure_ascii=False),
            created_at=created,
            updated_at=updated,
        )
    )
    return 1


def import_slot(snapshot):
    slot = AgentWorkspaceSlot.query.filter_by(id=snapshot["slot"]).with_for_update().one_or_none()
    require(
        slot
        and slot.user_id
        and slot.workspace_id == snapshot["workspace"]
        and slot.generation == snapshot["generation"],
        "Active workspace lease disagrees with snapshot",
    )
    projects = {}
    new_projects = 0
    for key, row in snapshot["projects"].items():
        project_id, added = import_project(slot.user_id, slot.workspace_id, key, row)
        projects[key] = project_id
        new_projects += added
    db.session.flush()
    new_chats = sum(
        import_chat(slot.user_id, slot.workspace_id, key, row, projects)
        for key, row in snapshot["chats"].items()
    )
    return {
        "slot": slot.id,
        "projects": len(projects),
        "chats": len(snapshot["chats"]),
        "new_projects": new_projects,
        "new_chats": new_chats,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        snapshots = load_slots(sys.stdin.buffer)
        app = Flask(__name__)
        app.config.update(
            SQLALCHEMY_DATABASE_URI=os.environ["DATABASE_URL"],
            SQLALCHEMY_ENGINE_OPTIONS={"hide_parameters": True},
        )
        db.init_app(app)
        with app.app_context():
            result = [import_slot(snapshots[slot]) for slot in sorted(snapshots)]
            db.session.flush()
            if args.apply:
                db.session.commit()
            else:
                db.session.rollback()
        print(json.dumps({"applied": args.apply, "slots": result}))
    except InvalidSnapshot as error:
        sys.exit(str(error))
    except Exception as error:
        sys.exit(f"Legacy import failed ({type(error).__name__})")


if __name__ == "__main__":
    main()
