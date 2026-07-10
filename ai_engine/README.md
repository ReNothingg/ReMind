# AI engine prompts

All model-facing instructions live in Markdown. Python code only selects templates and injects runtime values.

- `prompt.md` contains the base system prompt and always-available tool instructions.
- `user.md` contains account, personalization, and request metadata placeholders.
- `context/*.md` contains conditional runtime context such as Canvas, BeatBox, and active Mind data.
- `tools/*.md` contains tool-specific prompts and router sections.

Templates use `{{PLACEHOLDER_NAME}}` values rendered by `prompt_templates.py`. Markdown files are read for every request, so prompt edits do not require an application restart.

Model registry values, protocol keys, limits, logs, and user-facing runtime errors remain in Python because they are application behavior rather than model instructions.
