#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /absolute/path/to/backup.sql" >&2
  exit 2
fi

backup_path=$1
case "$backup_path" in
  /*) ;;
  *) echo "backup path must be absolute and outside the repository" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$backup_path")"
docker compose exec -T database sh -c \
  'pg_dump --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$backup_path"
echo "backup written to $backup_path"
