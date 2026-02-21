def echo(_, payload):
    return {
        "reply": (
            payload
            if isinstance(payload, str)
            else (
                payload.get("message") or payload.get("text", "")
                if isinstance(payload, dict)
                else str(payload)
            )
        )
    }

def echo_stream(_, payload):
    import time, json

    text = ""
    if isinstance(payload, dict):
        text = payload.get("message", "")
    elif isinstance(payload, str):
        text = payload
    for i in range(0, len(text), 40):
        chunk = text[i : i + 40]
        yield {"reply_part": chunk}
        time.sleep(0.04)
    import re

    m = re.search(r"\[WIDGET:(?:'|\")?(beatbox|quiz|spinwheel)(?:'|\")?\]", text, re.I)
    if m:
        tag = m.group(1).lower()
        for step in range(3):
            state = {"step": step + 1, "progress": (step + 1) / 3}
            yield {"widget_update": {"tag": tag, "state": state}}
            time.sleep(0.08)
    yield {"images": []}
