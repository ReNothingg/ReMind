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
| `db` | PostgreSQL database |
| `redis` | Sessions, queue broker и runtime cache |

Обязательные environment values:

```env
SECRET_KEY=replace-with-a-long-random-secret
DB_PASSWORD=replace-with-a-strong-db-password
REDIS_PASSWORD=replace-with-a-strong-redis-password
GEMINI_API_KEY=your-gemini-api-key
BACKEND_URL=https://your-domain.example
```

Опциональные интеграции:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
TELEGRAM_BOT_TOKEN=
```

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
