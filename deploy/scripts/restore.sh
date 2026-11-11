#!/usr/bin/env bash
# Restore a pg_dump file. DESTRUCTIVE: replaces the current database contents.
#   ./scripts/restore.sh backups/lexuz-20260101T000000Z.dump
set -euo pipefail
cd "$(dirname "$0")/.."
DUMP=${1:?usage: restore.sh backups/<file>.dump}
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"
read -r -p "Restore $DUMP over the live database? Type 'restore' to continue: " ok
[ "$ok" = "restore" ] || { echo aborted; exit 1; }
$COMPOSE stop api worker beat
$COMPOSE exec -T postgres pg_restore -U lexuz -d lexuz --clean --if-exists --no-owner "/backups/$(basename "$DUMP")"
$COMPOSE up -d api worker beat
echo "restored. Check: curl -fsS https://\$DOMAIN/health/ready"
