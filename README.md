# Print Fornece — Python 3.14 + Django 6.0

Sistema de gestão de pedidos, fluxo de produção Kanban, controle financeiro, despesas, relatórios e notificações.

Reescrito e refatorado de PHP para **Python 3.14** e **Django 6.0**. Todo o código legado em PHP foi removido e substituído por uma arquitetura Django limpa e modular.

---

## 🚀 Como Executar em Produção com Docker (Recomendado)

O projeto está totalmente pré-configurado para execução em contêineres Docker utilizando **Docker Compose**, **Gunicorn**, **WhiteNoise** e **MariaDB 10.11**.

### 1. Clonar o repositório
```bash
git clone https://github.com/Fawlerr/print-fornece.git
cd print-fornece
```

### 2. Configurar o arquivo de ambiente (`.env`)
Copie o modelo de ambiente `.env.example` para `.env` e configure suas credenciais de produção:
```bash
cp .env.example .env
```
Exemplo de conteúdo do `.env`:
```env
SECRET_KEY=sua-chave-secreta-super-segura
DEBUG=false
ALLOWED_HOSTS=*
APP_PORT=8080
TIMEZONE=America/Fortaleza

DB_HOST=db
DB_PORT=3306
DB_NAME=print_fornece
DB_USER=print_user
DB_PASSWORD=senha-do-banco-segura
DB_ROOT_PASSWORD=senha-root-segura

ADMIN_EMAIL=admin@printfornece.com.br
ADMIN_PASSWORD=admin-senha-segura
ADMIN_NAME=Administrador
```

### 3. Iniciar a aplicação
Suba os containers da aplicação Django e do MariaDB com um único comando:
```bash
docker compose up -d --build
```

O container executará automaticamente via `docker/entrypoint.sh`:
- Aguardará a disponibilidade do banco de dados MariaDB.
- Executará todas as migrações do banco (`python manage.py migrate`).
- Coletará os arquivos estáticos (`python manage.py collectstatic --noinput`).
- Verificará e criará o usuário **Administrador Inicial** com as credenciais definidas no `.env`.

Acesse a aplicação no navegador em: `http://localhost:8080` (ou na porta configurada em `APP_PORT`).

---

## 🛠️ Execução Local para Desenvolvimento (Sem Docker)

### Requisitos:
- **Python 3.14** (ou 3.12+)

### Passo a passo:

1. **Criar e ativar o ambiente virtual (venv)**:
   ```bash
   python -m venv .venv
   
   # No Linux/macOS:
   source .venv/bin/activate
   
   # No Windows (PowerShell):
   .\.venv\Scripts\Activate.ps1
   ```

2. **Instalar dependências**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Executar migrações do banco de dados**:
   ```bash
   python manage.py migrate
   ```

4. **Criar usuário Administrador inicial**:
   ```bash
   python manage.py create_admin
   ```

5. **Iniciar o servidor de desenvolvimento**:
   ```bash
   python manage.py runserver 127.0.0.1:8000
   ```

Acesse a aplicação em: `http://127.0.0.1:8000`
- **E-mail inicial**: `admin@printfornece.com.br`
- **Senha inicial**: `admin123456` (ou a definida em `ADMIN_PASSWORD`)

---

## 🧪 Suíte de Testes Automatizados

O projeto conta com testes unitários e de integração abrangendo autenticação, controle de permissões por perfil, CRUD de pedidos, upload seguro de arquivos, fluxo de produção (Kanban), despesas e relatórios.

Para executar os testes:
```bash
python manage.py test tests
```
Ou via `pytest`:
```bash
pytest
```

---

## 📂 Estrutura do Projeto

```text
print-fornece/
├── apps/
│   ├── accounts/       # Usuário customizado, perfis, autenticação, hasher legado e permissões
│   ├── orders/         # Pedidos, anexos seguros, observações e histórico
│   ├── production/     # Kanban de produção e máquina de estados de etapas
│   ├── expenses/       # Registro e controle de despesas operacionais
│   ├── dashboard/      # Métricas e indicadores da visão geral
│   ├── reports/        # Filtros, métricas e exportação de CSV
│   ├── notifications/  # Notificações do sistema e polling
│   ├── audit/          # Trilha de auditoria das ações
│   └── payments/       # Estrutura para integração futura de cobranças (Stone)
├── config/             # Configurações do Django (settings/, urls.py, wsgi.py, asgi.py, health.py)
├── templates/          # Templates HTML5 modernos e responsivos (tema dark)
├── static/             # CSS nativo e JS do sistema (estilização e interações)
├── media/              # Diretório de uploads e anexos de pedidos
├── database/           # Esquemas de banco SQL legados
├── docker/             # Script de entrada (entrypoint.sh)
├── Dockerfile          # Imagem de produção otimizada para Python 3.14
├── compose.yml         # Orquestração de containers Django + MariaDB 10.11
├── manage.py           # Utilitário de comando do Django
├── pytest.ini          # Configuração do test runner pytest
└── requirements.txt    # Dependências do projeto Python 3.14
```

---

## 🔐 Segurança e Produção

- **Upload de Arquivos**: Anexos de pedidos são armazenados com nomes mascarados via UUID e validados quanto ao tipo de conteúdo/MIME type, impedindo o upload de scripts executáveis.
- **Hashes Legados**: O sistema possui hasher customizado (`PHPBcryptPasswordHasher`) que aceita e re-criptografa senhas migradas do PHP no primeiro login.
- **Controle de Acesso (RBAC)**: Rotas financeiras e administrativas (Dashboard, Despesas, Relatórios, Usuários) são restritas a usuários com perfil `Administrador`.
