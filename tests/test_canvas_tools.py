from services.canvas_tools import process_canmore_calls


def test_bare_create_arguments_in_canmore_fence_create_canvas_textdoc():
    raw_reply = """Готовлю интерактивный сайт.

```Canmore
{"name":"maze-generator","type":"code/html","content":"<!doctype html><button id='new'>Новый лабиринт</button>"}
```

Готово.
"""

    result = process_canmore_calls(raw_reply)

    assert len(result.updates) == 1
    assert result.updates[0]["action"] == "create_textdoc"
    assert result.textdoc is not None
    assert result.textdoc["name"] == "maze-generator"
    assert result.textdoc["type"] == "code/html"
    assert "Новый лабиринт" in result.textdoc["content"]
    assert "Canmore" not in result.reply
    assert "maze-generator" not in result.reply
    assert result.reply == "Готовлю интерактивный сайт.\n\n\n\nГотово."


def test_invalid_canmore_fence_is_never_exposed_as_chat_content():
    raw_reply = "До вызова.\n\n```canmore\n{not valid json}\n```\n\nПосле вызова."

    result = process_canmore_calls(raw_reply)

    assert result.updates == []
    assert "not valid json" not in result.reply
    assert "```canmore" not in result.reply.lower()
    assert "До вызова." in result.reply
    assert "После вызова." in result.reply
