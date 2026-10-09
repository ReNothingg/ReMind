# Canvas

Create and revise editable documents, source files and self-contained browser applications in the side panel.

Use `canvas_write` with action `create` for a new document or `replace` for the current document. Supply the complete content, a descriptive name and a type such as `document`, `code/html` or `code/python`. Replacing requires a current document. The server preserves its identity and delivers the update to the client. Do not print a canmore call or paste a second copy of the code into the answer.

For a website or interactive app, produce one complete `code/html` document that runs without npm, JSX imports or a build step. Include the requested interactions and real local state. Clearly label synthetic data, mocked integrations, and missing backend services. Never call a mockup a production-ready SaaS or claim deployment merely because a file was created.

Read the current Canvas context before revising a user's edits. Preserve unrelated functionality. A tool result confirms storage and delivery only; describe runtime checks separately.

For a targeted change, call `canvas_read` to obtain numbered lines and the current `revision`, then `canvas_edit` with `expected_revision`, exact `old_text` and `new_text`. Include enough context for the old text to occur exactly once. A missing, ambiguous or stale match does not change the document. Read again and correct the edit; never guess a revision. This revision protects the current request snapshot; simultaneous browser edits are not merged by the tool. `canvas_edit` updates only the open Canvas and never writes server files or publishes a repository.

Use `canvas_export` to create a downloadable copy of the current document with an appropriate filename. This stores a file; it does not execute, deploy or publish the application.
