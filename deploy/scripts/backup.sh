#!/usr/bin/env bash
# PostgreSQL logical backup (custom format) + raw source snapshots. Keeps the last 14.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p backups
$COMPOSE exec -T postgres pg_dump -U lexuz -d lexuz -Fc -f "/backups/lexuz-$STAMP.dump"
$COMPOSE run --rm --no-deps --entrypoint tar worker -czf - -C /data snapshots > "backups/snapshots-$STAMP.tgz"
ls -1t backups/lexuz-*.dump | tail -n +15 | xargs -r rm --
ls -1t backups/snapshots-*.tgz | tail -n +15 | xargs -r rm --
echo "backup ok: backups/lexuz-$STAMP.dump"
