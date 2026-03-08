# AGENTS.md

Repository-wide instructions for coding agents working in `ReMind`.

## Project Snapshot

- ReMind is a full-stack AI chat application.
- Backend: Flask app factory in `app_factory.py`, thin route registration in `routes/api.py`, feature route modules in `routes/features/*`, domain services in `services/`, security and auth helpers in `utils/`, model adapters/prompts in `ai_engine/`.
- Frontend: React 19 + TypeScript + Vite 7 in `src/`. Newer work is gradually moving into `src/features/*`, while shared and older UI still lives in `src/components/*`, `src/hooks/*`, `src/context/*`, and `src/services/*`.
- Flask serves `dist/` when a frontend build exists; otherwise it falls back to `public/`.
- OpenAPI source is `openapi/openapi.json`; generated TypeScript types live in `src/generated/openapi.ts`.

## Working Principles

- Make the smallest coherent change that solves the task.
- Do not mix unrelated refactors with functional work unless explicitly asked.
- Check `git status` before editing. This repository may already contain user changes.
- Do not edit generated or build outputs by hand: `dist/`, `coverage/`, Playwright reports, logs, or `src/generated/openapi.ts`.
- Keep backend route handlers thin. Put domain logic in `services/` or focused helpers in `utils/`.
- Preserve existing response and error shapes. Backend errors should continue to use the established JSON response flow.

## Repository Map

- `src/`
  - `features/`: newer feature-scoped React code
  - `components/`: shared and legacy React UI
  - `services/`: frontend API layer and related unit tests
  - `hooks/`, `context/`: shared frontend behavior/state
  - `styles/`: global CSS, CSS variables, and layout/component styles
  - `i18n/`: locale loading and translation files
- `routes/features/`: Flask route registration per domain
- `services/`: backend business logic
- `utils/`: auth, security, privacy, validation, response helpers, observability
- `tests/`: backend pytest suite
- `tests/e2e/`: Playwright end-to-end tests
- `scripts/`: OpenAPI generation, security gate, e2e startup helpers
- `openapi/`: OpenAPI spec
- `database/`, `logs/`, `dist/`, `coverage/`, `test-results/`: runtime or generated artifacts; do not hand-edit

## Local Setup

Use the dev dependency set for backend work:

```text
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# Bash: source .venv/bin/activate
pip install -r requirements/dev.txt -c requirements/constraints.txt
npm ci
Copy-Item .env.example .env
```

If you only need runtime dependencies:

```bash
pip install -r requirements/runtime.txt -c requirements/constraints.txt
```

## Formatting And Style

- Python formatting is enforced by Black and Ruff with a `100` character line length and Python `3.11` target.
- Frontend formatting follows `.prettierrc`: single quotes, semicolons, `printWidth: 100`, `tabWidth: 2`.
- ESLint enforces React Hooks rules and TypeScript hygiene. `any` is only warned on, but avoid introducing it unless there is a real boundary reason.
- Use the import style already present in the touched file. Both relative imports and the `@ -> /src` alias are available, but the codebase is still mixed.
- Avoid broad formatting-only churn in unrelated files.

## Run Commands

- Backend: `python main.py`
- Frontend dev against a local backend: `npm run dev -- --port 5173`
- Production-like local run: `npm run build` then `python main.py`
- Docker config validation: `docker compose config`

Important: `vite.config.ts` defaults Vite to port `5000`, and Flask also binds to `5000`. Do not try to run both unchanged at the same time.

## Quality Commands

Frontend:

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit`
- `npm run test:unit:coverage`
- `npm run build`
- `npm run openapi:check`
- `npm run openapi:generate`

Backend:

- `ruff check .`
- `black --check .`
- `mypy app_factory.py routes utils services`
- `pytest`
- `pytest --cov=routes --cov=services --cov=utils --cov-report=term-missing --cov-fail-under=70`

End-to-end:

- First-time browser install: `npm run test:e2e:install`
- E2E suite: `npm run test:e2e`

Notes:

- `npm run test:e2e` starts its own backend via `scripts/e2e/run_server.py`.
- Flask-integrated frontend testing should use a fresh `npm run build` because stale `dist/` output can hide or reintroduce bugs.

## Frontend Guidance

- Prefer extending an existing feature folder in `src/features/<feature>` when one already exists.
- Use shared UI from `src/components/*` only when the change is truly cross-feature.
- Keep typed props and local interfaces close to the component unless a type is broadly shared.
- Follow the existing frontend stack: React function components, hooks, `react-i18next`, semantic class names, shared CSS files, and CSS variables.
- Do not rewrite CSS-heavy areas into Tailwind utility soup unless the file already follows that style. The project imports `src/styles/tailwind.css`, but most UI is still driven by regular CSS files under `src/styles/`.
- Respect guest, authenticated, shared, and read-only states. Header, rail, chat, auth modal, and share flows are tightly connected.
- If you change API behavior on the frontend, update related tests in `src/services/*.test.ts` or nearby targeted tests.
- If you add user-facing copy, update `src/i18n/locales/en/common.json`. Only add other locales when you can do so safely; missing locales fall back to English.
- `src/features/**/*` is checked with a stricter TypeScript config than the rest of `src/`. Do not assume a green typecheck means all legacy folders are equally strict.

## Backend Guidance

- Register new endpoints through the relevant module in `routes/features/*`. Keep `routes/api.py` as a thin registrar.
- Put business rules in `services/` where possible.
- Preserve security-sensitive behavior in:
  - `utils/auth.py`
  - `utils/session_security.py`
  - `utils/csrf_protection.py`
  - `utils/secure_upload.py`
  - `utils/input_validation.py`
  - `utils/idor_protection.py`
  - `utils/rate_limiting.py`
  - `utils/privacy.py`
- Do not weaken validation, auth, upload checks, privacy operations, or audit/security flows without explicit instruction.
- Keep API failures on the established response format instead of inventing ad hoc payloads.
- When changing auth, privacy, sessions, uploads, health, or sharing logic, add or update pytest coverage in `tests/`.
- Backend tests rely on test-specific environment overrides from `tests/conftest.py`; preserve that pattern when adding new configuration-sensitive behavior.
- If you add a new environment variable or service dependency, update `config.py`, `.env.example`, and deployment-related files when applicable.

## OpenAPI And Generated Types

- Treat `openapi/openapi.json` as the source of truth for schema-driven frontend typing.
- Do not hand-edit `src/generated/openapi.ts`.
- After changing the OpenAPI spec, run `npm run openapi:generate`, then update affected frontend consumers and tests.
- Before finishing an API-shape change, run `npm run openapi:check`.

## Testing Expectations By Change Type

- UI-only change: run `npm run lint` and at least one of `npm run test:unit` or `npm run build`.
- Frontend state or API client change: run `npm run lint`, `npm run typecheck`, and relevant Vitest coverage.
- Backend route or service change: run `ruff check .`, `black --check .`, `mypy app_factory.py routes utils services`, and targeted `pytest`.
- Cross-stack, auth, sharing, or session-history flow: run `npm run build`, relevant `pytest`, and `npm run test:e2e` when feasible.
- Schema change: run OpenAPI generation/check plus frontend build/tests.

## CI Awareness

CI currently runs:

- secret scanning
- Ruff
- Black format check
- Mypy
- Pytest with coverage threshold
- TypeScript checks
- OpenAPI drift check
- ESLint
- Vitest with coverage
- frontend build
- Playwright e2e
- security tooling (`pip-audit`, `npm audit`, Bandit, Semgrep) enforced by `scripts/security_gate.py`

Do not introduce committed secrets, obvious high-severity security findings, or unnecessary dependency churn.

## Guardrails

- Never commit `.env`, secrets, API keys, private certificates, or user data dumps.
- Avoid touching `migrations/versions/*` unless the task is specifically about migrations.
- Avoid editing `dist/`, `coverage/`, logs, generated reports, or `node_modules/`.
- Preserve Conventional Commit style if asked to prepare commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`.
- Respect the existing repo layout. Do not invent new top-level directories for code that clearly belongs in an existing area.

## Known Project Quirks

- Vite and Flask both default to port `5000`; override the Vite port for concurrent local work.
- The frontend strict TypeScript config only covers `src/features/**/*`.
- Flask serves `dist/` if present, so stale builds can affect integrated debugging.
- Some repository docs contain Cyrillic text that may look garbled in a misconfigured PowerShell session; treat terminal encoding issues separately from file corruption.
