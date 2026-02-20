#!/bin/sh
set -eu

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"

while true; do
  timestamp="$(date -u +%Y%m%d_%H%M%S)"
  outfile="/backups/taskbot_${timestamp}.sql.gz"

  if pg_dump -h postgres -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "$outfile"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup created: $outfile"
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup failed"
    rm -f "$outfile"
  fi

  find /backups -type f -name '*.sql.gz' -mtime +"${RETENTION_DAYS}" -delete
  sleep "${BACKUP_INTERVAL_SECONDS}"
done
