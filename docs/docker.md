# Docker

ReMind включает две Compose-конфигурации:

- `docker-compose.dev.yml` для локальной разработки с hot reload.
- `docker-compose.yml` для production-like стека с Nginx, Flask, Celery, PostgreSQL и Redis.

## Development stack

Первый запуск:

```bash
docker compose -f docker-compose.dev.yml up --build
```

Обычный запуск после сборки зависимостей:

```bash
docker compose -f docker-compose.dev.yml up
```

Или через npm:

```bash
npm run docker:dev
```

Сервисы:

| Сервис | URL / роль |
|---|---|
| `frontend` | `http://127.0.0.1:5173` |
| `backend` | `http://127.0.0.1:5000` |
| `worker` | Celery worker с Python file watcher |
| `db` | PostgreSQL 15 |
| `redis` | Redis 7 с append-only persistence |

Dev stack по умолчанию не читает основной `.env`. Он выставляет `LOAD_DOTENV=false` и использует Compose environment values, чтобы production cookie/domain/password настройки не ломали локальную разработку.

Для локальных override можно добавить `.env.dev`. Это необязательно.

## Когда нужен rebuild

Rebuild нужен после изменения:

- `package.json` или `package-lock.json`
- `requirements*.txt`
- файлы в `requirements/`
- `Dockerfile.dev`
- system packages или base image assumptions

Для обычных изменений frontend/backend кода достаточно:

```bash
docker compose -f docker-compose.dev.yml up
```

Vite отвечает за frontend HMR, Flask перезагружает backend, а `scripts/reload_on_change.py` перезапускает Celery worker при изменении Python-файлов.

## Production-like stack

Запуск:

```bash
docker compose up --build
```

Сервисы:

| Сервис | Роль |
|---|---|
| `nginx` | Public HTTP edge и static/API proxy |
| `app` | Flask application из production image |
| `worker` | Celery background worker |
| `telegram-bot` | Опциональный Telegram Bot API worker (profile `telegram`) |
| `db` | PostgreSQL database |
| `redis` | Sessions, queue broker и runtime cache |

Обязательные environment values:

```env
SECRET_KEY=replace-with-a-long-random-secret
DB_PASSWORD=replace-with-a-strong-db-password
REDIS_PASSWORD=replace-with-a-strong-redis-password
AI_PROVIDER_API_KEY=your-ai-provider-api-key
AI_PROVIDER_MODEL_NAME=your-ai-provider-model
BACKEND_URL=https://your-domain.example
```

Опциональные интеграции:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
APPLE_APP_BUNDLE_ID=synvexai.remind
# Web-вход включается только при наличии Services ID и точного HTTPS callback из Apple Developer.
APPLE_SERVICE_ID=
APPLE_WEB_REDIRECT_URI=https://your-domain.example/login/apple/callback
# Для обязательной server-side проверки web authorization code укажите готовый
# APPLE_CLIENT_SECRET либо APPLE_TEAM_ID + APPLE_KEY_ID + APPLE_PRIVATE_KEY_PATH.
APPLE_CLIENT_SECRET=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY_PATH=
TELEGRAM_CLIENT_ID=
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
```

Ниже переменные для тонкой настройки Telegram-бота:

```env
# Частота обновления draft-ответа в приватных чатах (секунды)
TELEGRAM_DRAFT_INTERVAL_SECONDS=0.55

# Размер истории диалога:
TELEGRAM_MAX_CONTEXT_MESSAGES=4
TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE=4

# Уровень мыслительной нагрузки (от "minimal" до "high"):
# - общий для всех Telegram-каналов
TELEGRAM_THINKING_LEVEL=low
# - отдельные режимы для обычных сообщений и inline
TELEGRAM_THINKING_LEVEL_MESSAGE=medium
TELEGRAM_THINKING_LEVEL_INLINE=minimal
```

Для нового Telegram Login откройте `@BotFather` → `Bot Settings` → `Web Login`,
добавьте origin сайта в Allowed URLs и скопируйте выданный Client ID в
`TELEGRAM_CLIENT_ID`. Имя и аватар бота используются Telegram на экране подтверждения
входа, поэтому оформите их как профиль ReMind.

Для Telegram-бота используйте тот же профиль бота, который связан с Web Login, и
заполните `TELEGRAM_BOT_TOKEN` и `TELEGRAM_BOT_USERNAME`. В BotFather включите:

- Groups и нужный режим Group Privacy;
- Inline Mode (`/setinline`) и inline feedback, чтобы ReMind получал
  `chosen_inline_result` и сохранял только действительно отправленные inline-ответы;
- Guest Mode, чтобы бот отвечал по `@username`, даже не состоя в чате.

После настройки запустите стек с профилем Telegram:

```bash
docker compose --profile telegram up --build
```

Compose сам формирует внутренние `DATABASE_URL`, `REDIS_URL` и Celery URL с хостами
`db` и `redis` из `DB_PASSWORD`/`REDIS_PASSWORD`. Значения этих URL в `.env` относятся
к запуску приложения напрямую на хосте и не подменяют адреса внутри контейнеров.

Для локального запуска `GITHUB_OAUTH_ENCRYPTION_KEY` может быть пустым: ReMind
детерминированно выводит совместимый Fernet-ключ из `SECRET_KEY`. Production Compose
по-прежнему требует отдельный ключ. Его можно сгенерировать командой:

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Worker сам проверяет `supports_inline_queries` и `supports_guest_queries`, публикует
локализованные команды и использует `sendRichMessageDraft`/`sendRichMessage` с
безопасным fallback на обычный текст для старых Bot API-серверов.

Для временного внешнего тестирования можно дополнительно включить Cloudflare Quick
Tunnel без открытия входящего порта и без Cloudflare-токена:

```bash
docker compose --profile telegram --profile tunnel up -d cloudflared
docker compose logs cloudflared
```

Выданный домен `https://*.trycloudflare.com` временный и меняется при пересоздании
контейнера. Quick Tunnel предназначен только для тестирования.

## Health Checks

Backend health:

```bash
curl http://127.0.0.1:5000/health
```

Nginx health в production-like stack:

```bash
curl http://127.0.0.1/health
```

Metrics:

```bash
curl http://127.0.0.1:5000/metrics
```

## Частые операции

Остановить dev stack:

```bash
npm run docker:dev:down
```

Посмотреть logs:

```bash
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml logs -f worker
```

Пересобрать dev stack:

```bash
npm run docker:dev:build
```

Сбросить dev volumes:

```bash
docker compose -f docker-compose.dev.yml down -v
```

Команда удалит локальные PostgreSQL и Redis данные dev stack.
