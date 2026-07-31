# Print Fornece — Django 6.0.7

## Aviso de hospedagem

Esta é uma aplicação Django real, com WSGI/Gunicorn; **ela não funciona no plano de hospedagem compartilhada Business/Web da Hostinger**. Esse plano não fornece Python, `pip` nem acesso root para manter um processo WSGI. Publique a pasta `django_app/` em uma Hostinger VPS ou em outra plataforma que ofereça Python 3.12+ e WSGI/ASGI. A versão PHP original continua preservada na raiz do repositório e não deve ser apagada até a validação da migração.

Django 6.0.7 requer Python 3.12, 3.13 ou 3.14. A aplicação foi preparada para MySQL 8.0.11+ ou MariaDB 10.6+, `utf8mb4`, InnoDB e modo SQL estrito. Referências: [Django 6.0](https://docs.djangoproject.com/en/6.0/releases/6.0/), [bancos suportados](https://docs.djangoproject.com/en/6.0/ref/databases/), [suporte da Hostinger ao Django](https://www.hostinger.com/br/support/1583678-o-django-e-suportado-na-hostinger/).

## Inventário e estratégia de migração

O legado PHP foi inventariado antes da implementação. Ele tem as tabelas `usuarios`, `pedidos`, `pedido_arquivos`, `pedido_historico`, `pedido_observacoes`, `pedido_etapas_historico`, `despesas`, `notificacoes`, `cobrancas` e `auditoria`. Não existe `notificacao_destinatarios` no SQL real.

O novo banco usa tabelas `pf_*`, de propósito diferentes das tabelas PHP. Assim, `migrate` jamais deve apontar para o banco PHP original. A importação lê um banco de origem separado e grava no novo banco, preservando IDs, relações, datas, decimais, status, históricos e auditoria. Anexos são copiados para `MEDIA_ROOT/order_attachments/` com novos nomes aleatórios e o vínculo do pedido é mantido.

Fluxo seguro:

1. Mantenha o PHP original intacto e exporte o banco legado com `mysqldump`/phpMyAdmin.
2. Crie um **novo** banco MySQL/MariaDB para Django, com `utf8mb4`.
3. Configure `.env` a partir de `.env.example` sem reutilizar segredos do código PHP.
4. Execute migrations no banco novo.
5. Rode a importação primeiro em `--dry-run`, revise o JSON, e só então a importação confirmada.
6. Compare as contagens e teste a nova aplicação antes do corte de DNS/tráfego.

## Estrutura

```
django_app/
├── apps/
│   ├── accounts/       # usuário customizado, login, recuperação e permissões
│   ├── orders/         # pedidos, anexos, observações, histórico e importador
│   ├── production/     # Kanban e transações de etapas
│   ├── expenses/       # despesas e cancelamento lógico
│   ├── dashboard/      # indicadores administrativos
│   ├── reports/        # filtros, métricas e CSV
│   ├── notifications/  # notificações internas
│   ├── audit/          # trilha de auditoria
│   └── payments/       # interface Stone inativa
├── config/settings/    # base, development e production
├── templates/          # templates Django que preservam o layout legado
├── static/             # CSS/JS, sem Node obrigatório
├── media/              # gerado no servidor; nunca versionar anexos
├── deploy/             # exemplos para VPS, Nginx e systemd
└── scripts/            # atalhos seguros da importação legada
```

## Execução local

Use Python 3.12+ e um ambiente virtual. SQLite é permitido somente no perfil `development` e nos testes isolados; **produção sempre usa MySQL/MariaDB**.

```bash
cd django_app
python3.12 -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Em Windows, crie `.env` copiando o exemplo pelo Explorador ou por um editor. Nunca publique `.env`, `media/` ou backups SQL.

## Configuração de produção

Defina `DJANGO_SETTINGS_MODULE=config.settings.production` e, no mínimo:

- `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`;
- `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT`;
- `DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True` e HTTPS;
- e-mail SMTP se a recuperação de senha for usada.

O `settings.production` recusa `SECRET_KEY` de desenvolvimento e banco sem nome. Use `python manage.py check --deploy` antes de abrir a aplicação ao público.

## Importação do PHP legado

O comando não aceita o mesmo banco como origem e destino. Fora de `--dry-run`, ele exige um backup existente e a confirmação explícita. Ele faz transações por lote, é idempotente e emite `imported`, `updated`, `rejected` e `missing_files`.

```bash
# 1. Validar leitura e formato, sem escrever
python manage.py import_legacy_data --dry-run \
  --source-name print_fornece_legacy --source-user legacy_reader \
  --source-host 127.0.0.1 --report-file reports/migration-dry-run.json

# 2. Após criar e conferir o dump da origem, importar no banco Django novo
python manage.py import_legacy_data \
  --source-name print_fornece_legacy --source-user legacy_reader \
  --backup-file /srv/backups/print_fornece_legacy.sql --confirm-backup \
  --upload-root /srv/legacy-print-fornece/uploads/pedidos \
  --report-file reports/migration-final.json

# 3. Conferir todas as contagens sem gravar nada
python manage.py validate_legacy_data --source-name print_fornece_legacy --source-user legacy_reader
```

Use `LEGACY_MYSQL_*` e `LEGACY_UPLOAD_ROOT` apenas no ambiente da migração, nunca no repositório. Se `missing_files` não estiver vazio, os respectivos registros continuam importados, mas sem download até que o arquivo seja restaurado do backup. Os scripts `scripts/migrate_legacy_data.py` e `scripts/validate_legacy_data.py` são atalhos para os mesmos comandos.

As senhas PHP bcrypt `$2y$` são mantidas em um hasher temporário no formato Django e verificadas sem descriptografia. Depois de um login válido, Django as atualiza para o hasher padrão PBKDF2. Não remova o hasher legado de `PASSWORD_HASHERS` enquanto houver contas importadas que ainda não entraram.

## Funcionalidades preservadas e endurecidas

- Login/logout com CSRF, recuperação e troca obrigatória de senha; usuário customizado com administrador/funcionário.
- Dashboard, pedidos, Kanban com drag-and-drop e botões acessíveis, anexos privados, notas, histórico, auditoria e notificações.
- Pagamento não pago/parcial/pago, prioridade, responsável, finalização, cancelamento lógico e restauração administrativa.
- Despesas, filtros, relatórios e exportação CSV com `DecimalField`; o dashboard mantém a regra histórica de faturamento integralmente pago, enquanto relatórios somam `valor_pago` real.
- Stone continua puramente estrutural: botões “Em breve”, serviço sem chamadas HTTP e webhook 503.
- Funcionários recebem 403 nas áreas administrativas/financeiras e não podem alterar os campos financeiros de pedidos existentes. A fila de produção continua compartilhada entre funcionários, como no legado, mas toda rota aplica permissão explícita por objeto.

## Publicação em VPS Hostinger

Os exemplos em `deploy/` são para uma VPS Linux, não para hospedagem compartilhada:

1. Crie usuário sem privilégios, diretório `/srv/print-fornece`, venv Python 3.12+ e banco MySQL novo.
2. Copie `deploy/env.example` para `/etc/print-fornece.env`, com permissão `0600`, preenchendo valores reais.
3. Instale dependências de compilação do `mysqlclient` (por exemplo, `default-libmysqlclient-dev`, `build-essential`, `pkg-config`, conforme a distribuição), depois `pip install -r requirements.txt`.
4. Instale os exemplos de `gunicorn.service.example` e `nginx.conf.example`, ajuste domínio/caminhos, habilite Nginx e obtenha HTTPS antes de habilitar redirecionamento HTTPS/HSTS.
5. Rode `migrate`, `collectstatic`, `createsuperuser`, a validação da migração, e então inicie o serviço. O `deploy.sh.example` não faz operações destrutivas, mas deve ser revisado antes de uso.
6. Exponha `/health/` apenas ao monitoramento/rede necessária; ele retorna somente `{"status":"ok"}`.

Como alternativa, uma plataforma Python com WSGI/ASGI pode hospedar o app. O MySQL da Hostinger só poderá continuar externo se a conta/VPS permitir acesso remoto e o firewall aceitar a origem; confirme isso no hPanel antes da migração.

## Verificação

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py collectstatic --noinput
```

Sem um MySQL local, use a base SQLite isolada apenas para desenvolvimento/testes e execute as validações finais MySQL, importação, uploads e deploy em uma VPS de homologação. Não faça deploy, altere DNS nem execute a importação contra produção automaticamente.

