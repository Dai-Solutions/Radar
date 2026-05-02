#!/usr/bin/env bash
# Radar DB backup — Postgres pg_dump veya SQLite copy.
# Kullanım:
#   ./scripts/backup.sh                       # ./backups/ altına yazar
#   BACKUP_DIR=/var/backups ./scripts/backup.sh
#   RETENTION_DAYS=14 ./scripts/backup.sh     # eski dosyaları temizler
#
# Cron örneği (her gece 03:00):
#   0 3 * * * cd /home/daiadmin/apps/radar && ./scripts/backup.sh >> /var/log/radar-backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TS="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

# .env'den DATABASE_URL oku
if [ -f "$PROJECT_ROOT/.env" ]; then
  DATABASE_URL="$(grep -E '^DATABASE_URL=' "$PROJECT_ROOT/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")"
fi

if [ -n "${DATABASE_URL:-}" ] && [[ "$DATABASE_URL" == postgresql* ]]; then
  OUT="$BACKUP_DIR/radar_pg_${TS}.sql.gz"
  echo "[$(date)] Postgres backup → $OUT"
  pg_dump "$DATABASE_URL" --no-owner --no-acl | gzip > "$OUT"
elif [ -f "$PROJECT_ROOT/data/radar.db" ]; then
  OUT="$BACKUP_DIR/radar_sqlite_${TS}.db.gz"
  echo "[$(date)] SQLite backup → $OUT"
  gzip -c "$PROJECT_ROOT/data/radar.db" > "$OUT"
else
  echo "ERROR: Ne DATABASE_URL ne de data/radar.db bulundu" >&2
  exit 1
fi

SIZE="$(du -h "$OUT" | cut -f1)"
echo "[$(date)] Backup OK ($SIZE)"

# Retention: RETENTION_DAYS'ten eski dosyaları sil
DELETED=$(find "$BACKUP_DIR" -type f \( -name 'radar_pg_*.sql.gz' -o -name 'radar_sqlite_*.db.gz' \) \
  -mtime +"$RETENTION_DAYS" -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
  echo "[$(date)] Retention: $DELETED eski dosya silindi (>$RETENTION_DAYS gün)"
fi
