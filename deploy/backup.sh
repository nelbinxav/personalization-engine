#!/usr/bin/env bash
# Back up the database and the .env that unlocks it.
#
#   deploy/backup.sh [output-dir]      default: ./backups
#
# Both halves matter: provider keys in Mongo are encrypted with APP_SECRET_KEY
# from .env, so a database dump without the matching .env restores everything
# except the keys. Keeps the newest $KEEP backups.
#
# Restore on a fresh machine (same APP_SECRET_KEY in .env first):
#   docker compose up -d mongo
#   docker compose exec -T mongo mongorestore --archive --gzip --drop < backups/<stamp>/mongo.archive.gz
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="${1:-backups}"
KEEP="${KEEP:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT/$STAMP"

mkdir -p "$DEST"
chmod 700 "$OUT"

docker compose exec -T mongo mongodump --archive --gzip --quiet > "$DEST/mongo.archive.gz"
cp .env "$DEST/env"
chmod 600 "$DEST/env" "$DEST/mongo.archive.gz"

# A zero-byte dump means mongodump failed quietly; do not rotate a good
# backup out in favour of it.
if [ ! -s "$DEST/mongo.archive.gz" ]; then
  echo "Backup failed: empty dump at $DEST" >&2
  exit 1
fi

ls -1d "$OUT"/*/ 2>/dev/null | sort -r | tail -n "+$((KEEP + 1))" | while read -r old; do
  rm -rf "$old"
done
echo "Backed up to $DEST ($(du -h "$DEST/mongo.archive.gz" | cut -f1))"
