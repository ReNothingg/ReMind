FROM node:26-alpine AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY vite.config.ts tsconfig.json tsconfig.node.json ./
COPY src ./src
COPY public ./public
COPY index.html ./
RUN NODE_OPTIONS=--max-old-space-size=2048 npm run build
FROM node:26-bookworm-slim AS workspace
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1002 codex \
    && useradd --uid 1002 --gid 1002 --home-dir /data/codex-home --no-create-home --shell /usr/sbin/nologin codex
WORKDIR /opt/remind/codex
COPY integrations/codex/package*.json ./
RUN npm ci --include=optional --ignore-scripts --no-audit --no-fund \
    && node_modules/.bin/codex --version \
    && npm cache clean --force
COPY integrations/codex/*.mjs ./
ENTRYPOINT ["/usr/bin/tini","--"]

FROM python:3.14-slim AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libpng-dev \
    libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY requirements ./requirements
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt
FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=backend.app_factory:create_app \
    FLASK_ENV=production \
    FLASK_DEBUG=0
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libatomic1 \
    libstdc++6 \
    libjpeg62-turbo \
    zlib1g \
    libpng16-16 \
    libfreetype6 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /var/cache/apt/archives/*

COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
COPY --from=builder /app/requirements ./requirements

RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY . .
COPY --from=frontend /app/dist ./dist
RUN addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --ingroup app --home /app app \
    && chmod -R a+rX /app \
    && mkdir -p /app/database /app/logs /app/upload \
    && chown app:app /app/database /app/logs /app/upload \
    && chmod 700 /app/database /app/logs /app/upload
USER app

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["gunicorn", "-b", "0.0.0.0:5000", "wsgi:application", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--access-logformat", "%(t)s \"%(m)s %(H)s\" %(s)s %(b)s", "--error-logfile", "-"]
