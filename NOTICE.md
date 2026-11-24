# ReMind Notices

This notice clarifies project-level licensing, commercial licensing, branding, and private infrastructure boundaries. It does not replace the GNU Affero General Public License v3.0.

## Code License

The ReMind source code in this repository is licensed under GNU AGPL-3.0-only, unless a file states a different license.

Commercial use is allowed only under the terms of AGPL-3.0-only. AGPL allows commercial use, hosting, selling support, and charging for access, but it also requires compliance with its copyleft and network source-disclosure obligations.

If you modify ReMind and make it available to users over a network, you must offer those users access to the Corresponding Source of your modified version as required by AGPL-3.0-only.

## Commercial Licensing

If you want to use ReMind or parts of it in a proprietary product, closed-source service, hosted commercial platform, or without AGPL source-disclosure obligations, you must obtain a separate commercial license from ReNothingg.

Contact: [Telegram: @daich](https://t.me/daich)

## Trademark and Branding

The name "ReMind", the ReMind logo, visual identity, domains, official accounts, and official project branding are not licensed under AGPL-3.0-only.

You may not use the ReMind name, logo, branding, or official identity to promote modified versions, forks, commercial services, or derivative products without explicit written permission from ReNothingg.

Forks and modified versions must not imply that they are official ReMind releases, endorsed by ReNothingg, or connected to the official ReMind project unless written permission has been granted.

Official ReMind/ReNothingg identity channels include:

- Telegram contact: [@daich](https://t.me/daich)
- Telegram channel: [Re4Chan](https://t.me/Re4Chan)
- YouTube: [@ReNothinggg](https://www.youtube.com/@ReNothinggg)
- TikTok: [@renothingg](https://www.tiktok.com/@renothingg)
- X/Twitter: [@BLOOTBER515](https://x.com/BLOOTBER515)
- GitHub: [ReNothingg](https://github.com/ReNothingg)
- Steam: [Arbuzekkk](https://steamcommunity.com/id/Arbuzekkk)

## Private Production Materials

The public repository does not grant rights to any private production infrastructure, deployment configuration, secrets, billing systems, analytics, moderation systems, anti-abuse systems, model routing, private prompts, private model configuration, databases, operational scripts, or other non-public ReMind materials.

Those materials are not part of the open source distribution unless they are explicitly published in this repository under a stated license.

## Speech Synthesis Interoperability

The speech synthesis integration interoperates with the same undocumented Google Translate endpoint used by the [gTTS project](https://github.com/pndurette/gTTS). gTTS is Copyright © 2014–2024 Pierre Nicolas Durette and contributors and is distributed under the MIT License. ReMind does not bundle the gTTS package.

## No Legal Advice

This notice is a project policy summary and is not legal advice. The controlling software license for covered code is the AGPL-3.0-only license in [LICENSE](LICENSE).


## DeepSeek model protocol

The request normalization and stream state machine in `backend/ai_engine/deepseek_messages.py` were ported from `packages/llm/llm-deepseek/src/serialize.ts` and `translate.ts` in [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), published as `@deepseek-ai/dsh-llm-deepseek@0.2.2-rc.5`. Copyright (c) 2026 DeepSeek. See [the MIT license](licenses/DEEPSEEK-HARNESS-MIT.txt).

The translator emits text and usage while retaining provider signatures and tool inputs for replay. The event handling follows the [DeepSeek Harness translation source](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/llm-deepseek/src/translate.ts).

The compatible-provider adapters use the indexed tool-call assembly, terminal handling, and replay separation from the MIT-licensed [Harness Pi stream translator](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/llm/llm-pi-ai/src/stream.ts) and [block assembler](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/llm/llm/src/assembler.ts). ReMind keeps the compatible wire formats and replays signed parts on the same route during tool execution.

Durable model context adapts the versioned [DeepSeek replay envelope](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/llm/llm-deepseek/src/replay.ts) and [Harness request-prefix binding](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/llm/llm-pi-ai/src/prefix-binding.ts). ReMind binds encrypted replay records to the private chat, model connection, capabilities, and saved history prefix.

Project instruction framing, UTF-8 budgeting, and precedence are adapted from [DeepSeek Harness Agent Instructions](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/agent-instructions/src/render.ts).

The project draft and first-send binding adapt the workspace-first selection and blank-session behavior of the MIT-licensed [Harness workspace navigation](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-workspace/src/client/navigation.ts) and [workspace membership](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/workspace/workspace/src/entity.ts). ReMind's project belongs to the account and supplies the normal chat's context and files.

The project row's folder, disclosure, and action positions adapt the MIT-licensed [Harness project row](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-workspace/src/client/rows/Rows.tsx). The ReMind settings shell ports active-section selection, the panel grid, and navigation focus behavior from the [Harness settings root](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-settings-general/src/client/SettingsRoot.tsx) and uses ReMind's controls, icons, and responsive layout.

Explicit chat attachments adapt the dialogue projection, UTF-8 retention, and untrusted context framing in the MIT-licensed [Harness session reference service](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/context/session-reference/src/index.ts) and [reference projection](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/context/session-reference/src/projection.ts). The ReMind message stores a revision pointer and resolves the captured dialogue through the owner's private history.

Conversation checkpoint boundaries and prefix validation are adapted from [DeepSeek Harness Compaction](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/region.ts).

The model summary directive, prior-checkpoint consolidation, and pressure calculation adapt the MIT-licensed [Harness summarizer](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/compaction/compaction-basic/src/summarizer.ts) and [compaction configuration](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/compaction/compaction-basic/src/config.ts). ReMind replays a bounded text projection through its own model adapters and validates the active history before saving a checkpoint.

Provider configuration fields, draft catalog discovery, and model ordering follow the DeepSeek Harness [provider editor](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-settings-models/src/client/ProviderEditor.tsx) and [model settings](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-settings-models/src/client/ModelsSection.tsx).

Catalog inheritance and optimistic revision checks follow the MIT-licensed [provider editor and catalog controls](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-settings-models/src/client/ProviderEditor.tsx). The composer’s model and effort navigation and multilingual search adapt the [model picker](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-model-selection/src/client/ModelSelect.tsx) and [text search](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/util/text-search/src/index.ts) from the same source.

Per-model capacities, input modalities, and reasoning options adapt the MIT-licensed [model row](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-settings-models/src/client/ModelRow.tsx). Pending and last-used chat selections follow the [session model selection projection](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/core/agent/src/model-selection.ts).

Skill frontmatter parsing and discovery follow the MIT-licensed [filesystem skill provider](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/skill/skill-filesystem/src/index.ts). On-demand loading and explicit slash invocation adapt the [session skill loader](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/skill/tool-skill/src/index.ts).

The project patch format and hunk matching adapt the MIT-licensed [patch parser](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/fs/fs-patch/src/parse.ts) and [patch applier](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/fs/fs-patch/src/apply.ts). The ReMind project library simulates the operations before the owner reviews and applies them.

The retry policy and DeepSeek Search and Fetch adapters apply the retry settings, request shapes, and result mappings from the MIT-licensed [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness).

The workspace execution and delegation settings adapt the Shell and Subagent controls from the same project. ReMind enforces these settings on its isolated file runner and on the task requests sent through its model registry.

The opt-in delegation route list and exact child route validation follow the MIT-licensed [Subagent settings fields](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-settings-subagent/src/client/SubagentModelSelectionFields.tsx) and [Subagent model selection](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/subagent/tool-subagent/src/model-selection.ts). ReMind rechecks owner authorization and the selected route before dispatching each delegated task.

Pipeline sequencing and text utilities adapt the MIT-licensed [virtual Shell interpreter](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/experimental/webworker-runtime/src/shell/interpret.ts) and [text program table](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/experimental/webworker-runtime/src/shell/programs/text.ts). ReMind uses its project's virtual names for input and publishes redirected output as a chat attachment.

The same virtual Shell interpreter's left-to-right conditional dispatch is used for the supported `scripts/*.sh` skill members. Positional arguments are bound as literal values before a script operates on the chat's staged inputs.

Fixed-rate and calendar occurrence resolution in `backend/services/automation_timing.py` was adapted from [DeepSeek Harness Schedule](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/schedule/schedule/src/domain.ts) under the same license.

The model-facing schedule operations in `backend/services/tools/automation_tools.py` follow the caller checks, destination mapping, and list/view/create/edit contract from [DeepSeek Harness Schedule Tools](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/schedule/tool-schedule/src/index.ts).
