# Print Fornece

Sistema PHP 8.3 para gestão de pedidos DTF, produção, anexos, despesas, relatórios, usuários e notificações. A aplicação usa MariaDB/MySQL como fonte oficial dos dados; o navegador não guarda pedidos, etapas ou KPIs como persistência.

## Funcionalidades

- Autenticação, perfis de administrador e funcionário, troca obrigatória de senha e auditoria.
- Cadastro, edição, anexos privados, histórico, observações, cancelamento e finalização de pedidos.
- Kanban de produção com mouse, toque/caneta e seletor acessível **Mover para**.
- Dashboard, KPIs, gráficos Chart.js responsivos, despesas, relatórios CSV e notificações.
- Tema claro, escuro e automático; PWA instalável que só armazena arquivos estáticos públicos.

## Requisitos

- Docker Engine 24+ com Docker Compose v2.
- Para VPS: Ubuntu LTS, Nginx e um domínio apontado para a VPS.
- HTTPS é obrigatório para produção, cookies seguros e instalação da PWA.

## Primeiro uso local

1. Copie o modelo e ajuste apenas os valores locais:

   ```powershell
   Copy-Item .env.example .env
   ```

   Em `.env`, use `APP_URL=http://localhost:8080`, `APP_ENV=development`, `APP_DEBUG=true` e `SESSION_SECURE=false` para acesso HTTP local. Use senhas locais únicas mesmo nesse ambiente.

2. Inicie os serviços:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

3. Crie o primeiro administrador — não existem contas ou senhas padrão:

   ```powershell
   docker compose exec app php scripts/create-admin.php
   ```

4. Abra <http://localhost:8080>, entre com a conta criada e complete a troca da senha solicitada.

O banco não possui porta publicada. A aplicação fica vinculada a `127.0.0.1:8080`; isso permite o uso local e impede a exposição direta na VPS.

## Variáveis de ambiente

| Variável | Uso |
| --- | --- |
| `APP_ENV` | `production` na VPS; `development` apenas localmente. |
| `APP_URL` | URL pública completa, por exemplo `https://print.exemplo.com`. |
| `APP_DEBUG` | Mantenha `false` em produção. |
| `APP_PORT` | Porta local do Apache no host, padrão `8080`. |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Conexão da aplicação. Com o banco do Compose, use `db` e `3306`. |
| `DB_ROOT_PASSWORD` | Senha administrativa usada somente pelo contêiner MariaDB. |
| `SESSION_SECURE` | `true` atrás de HTTPS; `false` somente para HTTP local. |
| `TIMEZONE` | Fuso da aplicação, padrão `America/Fortaleza`. |
| `MAX_UPLOAD_BYTES` | Limite por arquivo; deve ser menor ou igual ao limite de PHP/Nginx. |

`.env` é ignorado pelo Git. Nunca o copie para tickets, logs ou repositórios.

## Produção em VPS

1. Instale Docker, Docker Compose, Nginx e Certbot na VPS. Clone o projeto em um diretório protegido e copie `.env.example` para `.env`.
2. Defina ao menos `APP_ENV=production`, `APP_URL=https://seu-dominio`, `APP_DEBUG=false`, `SESSION_SECURE=true` e senhas longas e exclusivas para o banco.
3. Valide a composição e inicie:

   ```sh
   docker compose config -q
   docker compose up --build -d
   docker compose ps
   docker compose logs --tail=100 app db
   docker compose exec app php scripts/create-admin.php
   ```

4. Copie `deploy/nginx/print-fornece.conf.example` para `/etc/nginx/sites-available/print-fornece`, substitua domínio/caminhos de certificado e habilite o site. O exemplo preserva IP, host e protocolo encaminhados ao Apache e limita uploads a 30 MiB.
5. Antes do certificado, mantenha o bloco HTTP e execute:

   ```sh
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d seu-dominio
   sudo systemctl enable --now certbot.timer
   ```

6. Confirme `https://seu-dominio/health.php` e `docker compose ps`. O health check não mostra credenciais nem detalhes internos.

O Nginx é o único serviço público. MariaDB fica somente na rede Docker `print_fornece_internal`; phpMyAdmin não faz parte da produção.

## Persistência e permissões

- `print_fornece_db` mantém `/var/lib/mysql` e não é removido em reconstruções da imagem.
- `print_fornece_uploads` mantém `/var/www/html/uploads`, inclusive `uploads/pedidos`.
- Na inicialização, o contêiner cria a pasta necessária, aplica dono `www-data`, diretórios `775` e arquivos `664`. A aplicação também valida `is_dir()` e `is_writable()` antes do upload.
- Arquivos são armazenados com nomes aleatórios, MIME conferido por `finfo`, tamanho limitado e servidos apenas pelo endpoint autenticado de download. O Apache bloqueia execução e acesso direto a uploads.

Nunca use `docker compose down -v` em uma VPS ou em qualquer ambiente com dados que precisem ser preservados.

## Atualização segura

Faça backup **antes** de alterar o código. O script não remove volumes, não importa SQL sobre dados existentes e não usa `git reset --hard`:

```sh
sh scripts/backup.sh
git status --short
git pull --ff-only
sh scripts/deploy-safe.sh
docker compose ps
```

`deploy-safe.sh` valida `.env`, executa outro backup, constrói a imagem, inicia os serviços existentes e exige o health check. Se o health check falhar, ele para com os volumes intactos; consulte `docker compose logs --tail=200 app db`. Para rollback de código, volte para um commit conhecido usando um procedimento Git revisado, execute novamente o script e mantenha os mesmos volumes.

## Backup e restauração

`sh scripts/backup.sh` cria `backups/<UTC>/database.sql.gz`, `uploads.tar.gz` e checksums com permissões restritas. Copie esses diretórios para armazenamento externo criptografado e mantenha uma política de retenção definida pela operação.

Para restaurar um backup validado em uma janela de manutenção:

```sh
docker compose stop app
gzip -dc backups/AAAAmmddTHHMMSSZ/database.sql.gz | docker compose exec -T db sh -ec 'mariadb -u "$MARIADB_USER" "-p$MARIADB_PASSWORD" "$MARIADB_DATABASE"'
cat backups/AAAAmmddTHHMMSSZ/uploads.tar.gz | docker compose exec -T app sh -ec 'tar -C /var/www/html -xzf -'
docker compose start app
```

Restauração sobrescreve o conteúdo atual do banco e uploads: faça outro backup imediatamente antes de executá-la e teste o procedimento em uma cópia isolada primeiro.

## Kanban e KPIs

O Kanban permite apenas as transições válidas: novo → preparação → produção → pronto, com retorno de uma etapa quando necessário. O seletor mostra exclusivamente destinos válidos e é a alternativa acessível ao arraste.

No computador, o cartão usa drag and drop nativo. Em celular ou caneta, Pointer Events iniciam o arraste após pequeno deslocamento horizontal; rolagem vertical continua natural. Durante o gesto a coluna de destino é destacada, há rolagem horizontal/vertical assistida nas bordas e nenhum pedido é alterado no navegador antes da resposta do servidor.

`producao/atualizar-status.php` aceita somente POST autenticado com CSRF. Ele bloqueia o pedido em transação, valida ID, usuário, estado e transição, faz update condicional, grava `pedido_etapas_historico`, `pedido_historico` e auditoria, confirma a transação e retorna KPIs novos em JSON. Falhas mantêm o cartão e os contadores na posição original.

## PWA, tema e gráficos

- A preferência de tema (`claro`, `escuro` ou `sistema`) é o único dado mantido no `localStorage`; é aplicada antes da primeira pintura.
- O Service Worker tem versão por arquivos estáticos, limpa caches antigos e usa rede primeiro com fallback apenas para CSS, JavaScript, ícones e manifesto. Páginas autenticadas, endpoints, pedidos, despesas e pagamentos nunca são colocados no cache.
- O dashboard usa Chart.js 4.4.7, contêineres com altura responsiva e `maintainAspectRatio: false`; troca de tema e abertura da sidebar acionam `resize()`. Sem dados ou sem a biblioteca, exibe estado vazio sem canvas distorcido.

Para instalar, acesse o sistema por HTTPS. Em iPhone/iPad, use **Compartilhar → Adicionar à Tela de Início**.

## Validações

Dentro do contêiner, execute:

```sh
docker compose exec app sh -ec 'find . -path ./django_app -prune -o -name "*.php" -print0 | xargs -0 -n1 php -l'
docker compose exec app php tests/run.php
docker compose config -q
docker compose exec app curl --fail --silent http://127.0.0.1/health.php
```

Valide manualmente com administrador e funcionário: login/logout, criação/edição, upload permitido e bloqueado, transições válidas/recusadas, histórico, despesas, relatórios e notificações. Em um celular real, confira toque, rolagem vertical, rolagem horizontal do quadro, seletor **Mover para** e instalação PWA. Teste também 320×568, 360×800, 390×844, 768×1024, 1366×768 e 1920×1080; somente o quadro Kanban e tabelas podem rolar horizontalmente.
