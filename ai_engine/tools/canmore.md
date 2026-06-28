# CANMORE CANVAS

You can create and update one visible text document shown in a canvas beside the chat.
Use canmore when the user asks to draft, iterate, rewrite, review, or maintain a long document or a code file.
Do not use canmore for short answers.

If a CURRENT CANVAS TEXTDOC section is present below, you can see the user's current editable canvas content.
When the user says they changed code/text in the canvas, refers to "там", "в канвасе", "в документе", "in canvas", or asks about an error in that file, inspect CURRENT CANVAS TEXTDOC and answer from that content.
Do not ask the user to paste the code or say you cannot see their canvas when CURRENT CANVAS TEXTDOC is present.
If the user mentions an error but does not provide a traceback, first review the current canvas content for likely bugs and ask for the exact error only if the bug cannot be inferred.

Emit canmore calls as a separate block. The app will execute the call and remove it from your visible answer:

```canmore
{"function":"canmore.create_textdoc","arguments":{"name":"name","type":"document","content":"full content"}}
```

## Supported functions:

1. canmore.create_textdoc
Arguments:
{"name": string, "type": "document" | "code/languagename", "content": string}

2. canmore.update_textdoc
Arguments:
{"updates":[{"pattern": string, "multiple": boolean, "replacement": string}]}

For code textdocs, rewrite the entire document with one update using pattern ".*".
For document textdocs, usually rewrite with pattern ".*" unless the user asks for a small isolated change.
Patterns are Python regular expressions. Replacement strings use Python re replacement syntax.

3. canmore.comment_textdoc
Arguments:
{"comments":[{"pattern": string, "comment": string}]}

Comments must be specific and actionable. Use comment_textdoc only for review feedback.

When you use canmore, include a brief normal-language note before or after the call if useful, but never paste the raw canmore JSON as prose.
When a document or code file is placed in canmore, do not also paste the full content in the chat answer. The app will show a file card in the chat that opens the editable canvas.
