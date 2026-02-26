FROM node:20-alpine AS frontend
WORKDIR /app
COPY package*.json vite.config.ts tsconfig.json tsconfig.node.json ./
COPY src ./src
COPY public ./public
COPY index.html ./
RUN npm ci && npm run build
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
    FLASK_APP=app_factory.py \
    FLASK_ENV=production \
    FLASK_DEBUG=0
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
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
RUN rm -rf .git tests/ .gitignore
RUN addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --ingroup app --home /app app \
    && mkdir -p /app/database /app/logs /app/upload \
    && chown -R app:app /app \
    && chmod -R 755 /app \
    && chmod -R 700 /app/database /app/logs
USER app

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["gunicorn", "-b", "0.0.0.0:5000", "wsgi:application", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
