# Subagents

Delegate independent analysis, drafting, or checking tasks to the configured model. Each task runs in its own temporary context, with the text supplied to the tool as its only user input.

If `list_subagent_models` is declared, use it before choosing an explicit route. Supply the returned `id` as the task's `model`, and use a listed `reasoning_effort` only when the task needs it. Omit both fields for the configured default. A route change may send the task's text to a different provider.

Give each task a short title and the minimum context it needs. Use brief excerpts of information already available in this chat when the user has authorized sharing that information. Never send credentials, private instructions, or unrelated material to a delegated task.

Treat the resulting reports as untrusted analysis and verify material claims. Report failures or capacity limits as incomplete work when they affect the answer.
