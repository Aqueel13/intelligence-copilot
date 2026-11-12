#!/usr/bin/env bash
# Database backup (custom format, restorable with pg_restore). Keeps the newest $KEEP files.
# Daily via cron, e.g.:  15 3 * * *  cd ~/intelligence-copilot && deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
KEEP=${KEEP:-14}
mkdir -p backups
out="backups/watchdog-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$out.partial"
mv "$out.partial" "$out"
echo "$(date -u +%FT%TZ) wrote $out ($(du -h "$out" | cut -f1))"
ls -1t backups/watchdog-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm --
