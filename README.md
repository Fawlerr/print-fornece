# Print Fornece

Sistema PHP para gerenciar pedidos de DTF, produção, arquivos, pagamentos, despesas, relatórios, usuários e notificações.

## Executar localmente com Docker

### Pré-requisito

Instale e abra o [Docker Desktop](https://www.docker.com/products/docker-desktop/). No Windows, deixe-o em execução antes de continuar.

### Iniciar o sistema

No PowerShell, na pasta deste projeto, execute:

```powershell
docker compose up --build -d
```

Na primeira execução, o Docker cria os contêineres do Apache/PHP e MariaDB e importa automaticamente `database/print_fornece.sql`. Aguarde alguns segundos e abra:

<http://localhost:8080>

### Acesso inicial

| Perfil | E-mail | Senha |
| --- | --- | --- |
| Administrador | `admin@printfornece.local` | `password` |
| Funcionária demo | `ana@printfornece.local` | `password` |
| Funcionário demo | `bruno@printfornece.local` | `password` |

O administrador precisa alterar a senha no primeiro acesso. Troque ou remova as contas de demonstração antes de publicar o sistema.

## Comandos úteis

Ver os logs dos serviços:

```powershell
docker compose logs -f
```

Parar os serviços, preservando o banco e os anexos:

```powershell
docker compose stop
```

Iniciar novamente:

```powershell
docker compose start
```

Parar e remover os contêineres, preservando os dados:

```powershell
docker compose down
```

## Instalar como aplicativo (PWA)

Em produção, com HTTPS ativo, o cabeçalho exibirá **Instalar app** quando o navegador puder oferecer a instalação. No Android e no Windows, confirme a instalação no próprio navegador. No iPhone ou iPad, use **Compartilhar → Adicionar à Tela de Início**.

A PWA mantém em cache somente arquivos estáticos públicos (CSS, JavaScript, manifesto e ícones). Páginas autenticadas, pedidos, pagamentos, despesas e endpoints nunca são usados offline nem armazenados pelo Service Worker.

## Reiniciar o banco de demonstração

O SQL só é importado quando o banco é criado pela primeira vez. Para apagar **todos os dados locais** e recriá-los a partir de `database/print_fornece.sql`, pare os serviços e execute:

```powershell
docker compose down -v
docker compose up --build -d
```

O comando `down -v` remove o volume do MariaDB; essa ação é irreversível para os dados que ainda não foram exportados.

## Como o ambiente local funciona

- `app`: Apache com PHP 8.3, disponível na porta `8080`.
- `db`: MariaDB 10.11, disponível na porta `3306` para ferramentas locais de banco.
- O banco é persistido no volume Docker `print_fornece_db`.
- Os anexos enviados ficam em `uploads/pedidos/` no projeto e permanecem após reiniciar os contêineres.
- A configuração de desenvolvimento fica em `docker/php/config.local.php`; ela conecta o PHP ao MariaDB do Docker. As credenciais desse arquivo são apenas para uso local.

## Problemas comuns

Se a porta 8080 já estiver ocupada, altere `"8080:80"` em `compose.yml` para outra porta livre, como `"8081:80"`, e acesse a nova URL.

Se a porta 3306 já estiver ocupada por outro MySQL local, altere `"3306:3306"` para `"3307:3306"`. Isso não muda a conexão interna entre PHP e MariaDB.

Se o banco não subir, confirme que o Docker Desktop está em execução e consulte `docker compose logs db`.

## Publicação

O Docker local usa credenciais de desenvolvimento. Para produção, crie `config/config.local.php` a partir de `config/config.local.example.php` com as credenciais reais e mantenha esse arquivo fora do repositório.
