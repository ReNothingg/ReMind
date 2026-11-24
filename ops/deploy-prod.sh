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

compose() {
  if [ -n "${AGENT_POOL_OVERLAY:-}" ]; then
    docker compose -f docker-compose.yml -f docker-compose.prod.yml -f "$AGENT_POOL_OVERLAY" --profile telegram "$@"
  else
    docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile telegram "$@"
  fi
}

set -- agent-router
for service in $(compose config --services); do
  case "$service" in workspace-[0-9]*) set -- "$@" "$service" ;; esac
done
compose up -d --build "$@"
compose up -d --build --force-recreate --remove-orphans app worker telegram-bot python-runner nginx
compose exec -T app python -c 'from backend.services.github.app import github_app_private_key; assert github_app_private_key(), "GitHub App private key is unavailable to the application user"'
compose ps
compose logs --tail=160 app telegram-bot migrate
