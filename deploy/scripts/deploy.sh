#!/usr/bin/env bash
# Called by CD over SSH:  deploy.sh <image-ref>   e.g. ghcr.io/owner/lexuz-rag:3f2c1ab...
# One deploy at a time (flock). Backup -> migrate -> start -> smoke -> rollback app on failure.
set -euo pipefail
cd "$(dirname "$0")/.."
NEW_IMAGE=${1:?usage: deploy.sh <image-ref>}
exec 9>/tmp/lexuz-deploy.lock
flock -n 9 || { echo "another deploy is running"; exit 1; }

set -a; . ./.env; set +a
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
PREV_IMAGE=$(cat .current_image 2>/dev/null || true)

echo "pull $NEW_IMAGE"
docker pull "$NEW_IMAGE"

echo "backup before deploy"
./scripts/backup.sh

echo "migrate (expand-only migrations; see docs/deployment.md)"
APP_IMAGE="$NEW_IMAGE" $COMPOSE run --rm --no-deps api alembic upgrade head

echo "start"
APP_IMAGE="$NEW_IMAGE" $COMPOSE up -d --remove-orphans api worker beat nginx

smoke() {
  for _ in $(seq 1 30); do
    if curl -fsS "https://$DOMAIN/health/ready" >/dev/null && curl -fsS "https://$DOMAIN/api/v1/documents" >/dev/null \
       && curl -fsS "https://$DOMAIN/" | grep -q "LexUZ RAG"; then
      return 0
    fi
    sleep 3
  done
  return 1
}

if smoke; then
  echo "$NEW_IMAGE" > .current_image
  echo "deploy ok: $NEW_IMAGE"
else
  echo "smoke check FAILED"
  if [ -n "$PREV_IMAGE" ]; then
    echo "rolling application back to $PREV_IMAGE (database is NOT rolled back)"
    APP_IMAGE="$PREV_IMAGE" $COMPOSE up -d api worker beat
  fi
  exit 1
fi
