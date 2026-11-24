import re

from backend.services.tools.tool_protocol import ModelToolResult

CHAT_MEMORY_TOOLS = ("chat_history_search", "chat_history_read")


def execute_chat_memory(archive, name, arguments):
    if name == "chat_history_search":
        query = arguments["query"].strip()
        if not query:
            return ModelToolResult({"ok": False, "error": "invalid_history_query"})
        if not archive:
            return ModelToolResult({"ok": False, "error": "tool_not_available"})
        matcher = re.compile(re.escape(query), re.IGNORECASE)
        matches = []
        for number in range(len(archive), 0, -1):
            entry = archive[number - 1]
            text = entry["text"]
            if found := matcher.search(text):
                start = max(0, found.start() - 120)
                matches.append(
                    {
                        "message": number,
                        "role": entry["role"],
                        "offset": start,
                        "quote": text[start : found.end() + 240],
                    }
                )
                if len(matches) >= arguments.get("limit", 6):
                    break
        return ModelToolResult({"ok": True, "matches": matches})
    number = arguments["message"]
    if not 1 <= number <= len(archive):
        return ModelToolResult({"ok": False, "error": "history_message_unavailable"})
    entry = archive[number - 1]
    text = entry["text"]
    offset = arguments.get("offset", 0)
    if offset > len(text):
        return ModelToolResult({"ok": False, "error": "offset_out_of_range"})
    end = min(len(text), offset + arguments.get("max_characters", 6000))
    return ModelToolResult(
        {
            "ok": True,
            "message": number,
            "role": entry["role"],
            "text": text[offset:end],
            "next_offset": end if end < len(text) else None,
        }
    )
