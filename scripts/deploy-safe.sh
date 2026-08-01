#!/bin/sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

if [ ! -f .env ]; then
  echo "Crie .env a partir de .env.example antes de atualizar." >&2
  exit 1
fi

required_keys='APP_ENV APP_URL DB_NAME DB_USER DB_PASSWORD DB_ROOT_PASSWORD'
for key in $required_keys; do
  if ! grep -q "^${key}=." .env; then
    echo "A variável $key não foi definida em .env." >&2
    exit 1
  fi
done

if ! grep -q '^APP_ENV=production$' .env; then
  echo "O deploy seguro exige APP_ENV=production." >&2
  exit 1
fi

docker compose config -q
sh "$root_dir/scripts/backup.sh"
docker compose build --pull app
docker compose up -d

attempt=0
until [ "$attempt" -ge 12 ]; do
  if docker compose exec -T app curl --fail --silent http://127.0.0.1/health.php >/dev/null; then
    echo "Atualização concluída; banco e uploads foram preservados."
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 5
done

echo "O health check não confirmou a aplicação. Consulte: docker compose logs --tail=200 app db" >&2
exit 1
