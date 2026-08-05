#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ "${1:-}" = "--no-pull" ]; then
  SKIP_PULL=1
else
  SKIP_PULL=0
fi

if [ "$SKIP_PULL" -eq 0 ]; then
  git pull
fi

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile telegram \
  up -d --build --force-recreate --remove-orphans app worker telegram-bot nginx

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile telegram \
  ps

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile telegram \
  logs --tail=160 app telegram-bot migrate
