from services.canvas_tools import find_canmore_marker, process_canmore_calls


def test_create_textdoc_from_canmore_block_strips_call():
    raw_reply = """Готово.

```canmore
{"function":"canmore.create_textdoc","arguments":{"name":"Plan","type":"document","content":"One\\nTwo"}}
```
"""

    result = process_canmore_calls(raw_reply)

    assert result.reply == "Готово."
    assert result.textdoc
    assert result.textdoc["name"] == "Plan"
    assert result.textdoc["type"] == "document"
    assert result.textdoc["content"] == "One\nTwo"
    assert result.updates[0]["action"] == "create_textdoc"


def test_create_textdoc_from_json_code_block_strips_call():
    raw_reply = """Вот файл:

```json
{"function":"canmore.create_textdoc","arguments":{"name":"maze.py","type":"code/python","content":"print(1)"}}
```

Этот вызов `canmore.create_textdoc` создаст документ.
"""

    result = process_canmore_calls(raw_reply)

    assert result.reply == "Вот файл:"
    assert result.textdoc
    assert result.textdoc["name"] == "maze.py"
    assert result.textdoc["content"] == "print(1)"


def test_update_textdoc_uses_python_regex_with_dotall():
    current = {
        "name": "Component",
        "type": "code/javascript",
        "content": "const a = 1;\nconst b = 2;",
    }
    raw_reply = """
canmore.update_textdoc({"updates":[{"pattern":".*","multiple":false,"replacement":"const done = true;"}]})
"""

    result = process_canmore_calls(raw_reply, current)

    assert result.reply == ""
    assert result.textdoc
    assert result.textdoc["content"] == "const done = true;"
    assert result.updates[0]["action"] == "update_textdoc"


def test_comment_textdoc_appends_review_comments():
    current = {
        "name": "Spec",
        "type": "document",
        "content": "Ship the feature",
    }
    raw_reply = """Review added.
<canmore>
{"function":"canmore.comment_textdoc","arguments":{"comments":[{"pattern":"Ship","comment":"Clarify who owns the launch."}]}}
</canmore>
"""

    result = process_canmore_calls(raw_reply, current)

    assert result.reply == "Review added."
    assert result.textdoc
    assert result.textdoc["comments"][0]["pattern"] == "Ship"
    assert result.textdoc["comments"][0]["comment"] == "Clarify who owns the launch."


def test_find_canmore_marker_detects_stream_marker():
    assert find_canmore_marker("hello ```canmore\n{}") == 6
    assert find_canmore_marker('hello ```json\n{"function":"canmore.create_textdoc"') == 6
    assert find_canmore_marker("hello canmore.create_textdoc(") == 6
    assert find_canmore_marker("plain answer") == -1
