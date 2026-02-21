# Contributing to ReMind

Спасибо за интерес к проекту.

Этот документ задает единые правила для вкладов в код, документацию и процессы ReMind.

Связанные документы:

- `GOVERNANCE.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `docs/RELEASE_PROCESS.md`

## Scope

Мы принимаем вклад в:

- backend (`routes/`, `services/`, `utils/`, `ai_engine/`);
- frontend (`src/`, `public/`);
- инфраструктуру (`Dockerfile`, `docker-compose.yml`, `.github/`);
- документацию (`README.md`, `docs/`, policy-файлы).

## Before You Start

Перед началом работы:

1. Проверьте открытые issues и PR, чтобы не дублировать работу.
2. Если изменение заметно меняет поведение, сначала откройте issue с предложением.
3. Для security-проблем не создавайте публичный issue, используйте `SECURITY.md`.

## Local Setup

```bash
git clone https://github.com/SynvexAI/ReMind.git
cd ReMind
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm ci
cp .env.example .env       # Windows: Copy-Item .env.example .env
```

## Branching Strategy

- Базовая ветка: `main`
- Именование feature-веток:
1. `feat/<short-description>`
2. `fix/<short-description>`
3. `chore/<short-description>`
4. `docs/<short-description>`

Примеры:

- `feat/session-sharing`
- `fix/csrf-token-validation`
- `docs/readme-refresh`

## Commit Convention

Используйте Conventional Commits:

- `feat: add session slug validation`
- `fix: prevent empty chat payload`
- `docs: improve local setup section`
- `refactor: simplify auth response mapping`
- `chore: update github templates`

Желательно держать commit атомарным: один commit = одно логическое изменение.

## Code Style

### Python

- Пишите явный, безопасный и читаемый код.
- Не ослабляйте валидацию входных данных и security checks.
- Для ошибок API используйте согласованные форматы ответов.
- Старайтесь не смешивать рефакторинг и функциональные изменения в одном PR.

### Frontend (TypeScript/React)

- Следуйте текущей структуре компонентов/хуков.
- Не добавляйте тяжелые зависимости без обоснования.
- Проверяйте состояния загрузки/ошибок и сценарии guest/auth режимов.

## Required Checks Before PR

Минимальный pre-PR чек:

```bash
npm run build
python -m py_compile main.py app_factory.py routes/api.py utils/auth.py
```

Если меняли Docker/infra, дополнительно:

```bash
docker compose config
```

## Pull Request Rules

Каждый PR должен содержать:

1. Понятное описание проблемы и решения.
2. Ссылку на issue (если есть).
3. Описание рисков и обратной совместимости.
4. Список того, что протестировано.
5. Скриншоты/видео для заметных UI-изменений.

Рекомендация по размеру PR:

- до ~400 строк чистых функциональных изменений (если возможно);
- большие PR делите на серию логических частей.

## Security and Sensitive Data

- Никогда не коммитьте `.env`, ключи API, сертификаты, приватные токены.
- Не логируйте чувствительные данные пользователей.
- Для security-уязвимостей используйте private disclosure flow (`SECURITY.md`).

## Review Expectations

- Все изменения проходят code review.
- Поддерживается принцип: минимум один approve перед merge.
- Запрещено force-push в `main`.

## Changelog Discipline

- Любые user-facing изменения добавляйте в `docs/CHANGELOG.md`.
- Если изменение затрагивает security/infra, отдельно укажите impact в PR.
