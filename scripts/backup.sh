#!/bin/sh
set -eu
umask 077

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

if [ ! -f .env ]; then
  echo "Crie o arquivo .env antes de executar o backup." >&2
  exit 1
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$root_dir/backups/$timestamp"
install -d -m 700 "$backup_dir"

docker compose exec -T db sh -ec 'exec mariadb-dump --single-transaction --quick -u "$MARIADB_USER" "-p$MARIADB_PASSWORD" "$MARIADB_DATABASE"' | gzip -9 > "$backup_dir/database.sql.gz"
docker compose exec -T app sh -ec 'tar -C /var/www/html -czf - uploads' > "$backup_dir/uploads.tar.gz"

sha256sum "$backup_dir/database.sql.gz" "$backup_dir/uploads.tar.gz" > "$backup_dir/SHA256SUMS"
echo "Backup criado em $backup_dir"
