#!/bin/sh
set -eu

if [ "$#" -ne 2 ] || [ "$2" != "--confirm-replace-local-data" ]; then
  echo "usage: $0 /absolute/path/to/backup.sql --confirm-replace-local-data" >&2
  exit 2
fi

backup_path=$1
case "$backup_path" in
  /*) ;;
  *) echo "backup path must be absolute" >&2; exit 2 ;;
esac
test -f "$backup_path"

docker compose stop backend frontend
docker compose exec -T database sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  < "$backup_path"
docker compose up -d backend frontend
echo "local database restored from $backup_path"
