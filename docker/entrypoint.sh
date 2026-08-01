#!/bin/sh
set -e

echo "Aguardando inicialização do ambiente Django..."

# Executa migrações no banco MariaDB
echo "Executando migrações do banco de dados..."
python manage.py migrate --noinput

# Coleta arquivos estáticos para WhiteNoise
echo "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput

# Cria administrador inicial se necessário
echo "Verificando/Criando usuário administrador inicial..."
python manage.py create_admin

exec "$@"
