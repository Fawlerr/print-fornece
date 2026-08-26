#!/bin/sh
set -eu
umask 077

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

echo "[BACKUP] Executando rotina oficial de backup do Print Fornece..."
if command -v docker >/dev/null 2>&1 && docker compose ps app >/dev/null 2>&1; then
  docker compose exec -T app python manage.py backup --trigger=automatic "$@"
else
  python manage.py backup --trigger=automatic "$@"
fi
echo "[BACKUP] Concluído com sucesso."
