# Rebranding do Print Fornece

Guia aprovado: [guia-visual.html](guia-visual.html). Prints: `antes/` e `depois/` (1280 px e 390 px). Lighthouse: `lighthouse/`.

## Como a identidade está organizada

| Arquivo | Papel |
|---|---|
| `static/css/tokens.css` | **Fonte única** de cores, fontes, espaços, raios e sombras, nos temas escuro (padrão) e claro. Também redefine as variáveis antigas (`--panel`, `--green`…), para o CSS legado seguir os tokens. |
| `static/css/components.css` | Componentes (botões, campos, tabelas, cartões, etapas, Kanban, navegação, mensagens, diálogos) e regras de celular/tablet. Carregado por último. |
| `static/js/kanban-mobile.js` | Kanban no celular: abas por etapa, seletor "Mover para…" no card, botão de filtros. |
| `static/js/kanban-live.js` | Atualização ao vivo do Kanban (A6). |

As cores fixas que estavam escritas dentro dos templates (cerca de 2.700) foram trocadas pelos tokens equivalentes. Assim, os dois temas valem em todas as telas.

## Tema por usuário
- Campo `User.ui_theme` (`dark`/`light`), migração aditiva `accounts.0006_user_ui_theme`.
- Botão sol/lua no topo de todas as telas (`POST /accounts/theme/`).

## Telas (36)
Login, esqueci a senha, dashboard, novo pedido, editar pedido, Kanban, detalhe do pedido, clientes (lista, novo, detalhe), estoque (lista, novo insumo), caixa, caixa beta, despesas (lista, nova), 10 relatórios, usuários (lista, novo), perfil, trocar senha, configurações, notificações, relatos de bug, console Stone (dev), página do cliente (orçamento), nota térmica e fatura agrupada.

## Componentes
Botões (principal, secundário, perigo, aviso, pequeno), campos (texto, telefone, valor, data, seleção, caixa de seleção), tabelas com rolagem própria, cartões de indicador, selos de etapa e de pagamento, card do Kanban com faixa da etapa, selo APROVADO, abas, filtro de período, mensagens (sucesso, erro, aviso), diálogo/painel inferior, menu lateral, menu inferior no celular, esqueleto de carregamento e estado vazio.

## Lighthouse (antes × depois)

Medido no mesmo computador, com Lighthouse 12.6.1 e login real. O "antes" é o código commitado antes do rebranding (`lighthouse/antes-v3/`), e o "depois" é o estado final (`lighthouse/depois-v4/`).

| Página | Antes (Desemp. / Acess. / Boas práticas / SEO) | Depois |
|---|---|---|
| Kanban, celular | 100 / 96 / 100 / 91 | 98 / **100** / 100 / 91 |
| Kanban, computador | 100 / 96 / 100 / 91 | não concluiu (*) |
| Login, celular | 99 / 100 / 100 / 90 | 97 / 100 / 100 / 90 |
| Login, computador | 100 / 100 / 100 / 90 | 100 / 100 / 100 / 90 |
| Página do cliente, celular | 100 / 100 / 100 / 54 | 100 / 100 / 100 / 54 |
| Página do cliente, computador | 100 / 100 / 100 / 54 | 100 / 100 / 100 / 54 |

- O desempenho varia de uma medição para outra: o login no celular deu 97, 95 e 99 em três medições do "antes", e o Kanban no celular deu 98 e 100. Os valores do "depois" estão nessa faixa.
- A fonte dos títulos passou a ser servida pelo próprio sistema, e o corpo usa a fonte nativa do aparelho. Com as fontes do Google, o desempenho no celular caía para 92.
- O Kanban no celular já abre no modo de abas, sem deslocamento de layout (CLS 0,71 → 0).
- (*) O Kanban no computador, o novo pedido e os relatórios ficaram sem nota em pelo menos uma das rodadas: o Lighthouse estoura o tempo esperando a rede "parar", e essas telas fazem consultas periódicas (notificações, usuários online, Kanban ao vivo).
- SEO 54 na página do cliente é intencional: ela tem `noindex`, porque orçamentos não devem aparecer no Google.

## Fora do escopo desta etapa
- O módulo Stone (`static/pagamentos/`) mantém o CSS próprio; ele já usa a paleta escura.
- A nota térmica continua preto no branco (é impressão).
