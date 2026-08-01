#!/bin/sh
set -eu

upload_dir=/var/www/html/uploads/pedidos

if [ ! -d "$upload_dir" ]; then
  install -d -m 775 -o www-data -g www-data "$upload_dir"
fi

# Volumes nomeados e bind mounts podem iniciar como root. Ajuste somente esta
# árvore persistente para que o processo Apache (www-data) possa gravar.
chown -R www-data:www-data /var/www/html/uploads
find /var/www/html/uploads -type d -exec chmod 775 {} +
find /var/www/html/uploads -type f -exec chmod 664 {} +

if [ ! -d "$upload_dir" ] || ! su -s /bin/sh -c "test -w '$upload_dir'" www-data; then
  echo "A pasta de uploads não está disponível para escrita." >&2
  exit 1
fi

exec "$@"
