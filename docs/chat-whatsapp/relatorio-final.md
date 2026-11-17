# Relatório — Chat de WhatsApp e link de pagamento no cartão

> **Atualização de 17/11/2026 — provedor Umbler Talk.** Por decisão do dono do sistema, o provedor padrão do WhatsApp passou a ser a **API da Umbler Talk** (detalhes, rotas e passo a passo em [`umbler.md`](umbler.md)). A Evolution continua disponível por número. As chaves serão preenchidas depois no `.env`; o código está pronto e testado com a API simulada (20 testes específicos da Umbler).

Branch: `feat/chat-whatsapp-link-pagamento` (a partir da `main` em `5e45258`). Commitado e enviado ao GitHub em 17/11/2026 a pedido do dono do sistema, que vai preencher as chaves depois. Os testes reais (Umbler e sandbox do Pagar.me) ainda não rodaram — ver seção 9.

## 1. O que veio da Casa das Óticas

| Trazido / adaptado | Reescrito no padrão do Print | Ficou de fora |
|---|---|---|
| Normalização de telefone (DDI 55, 9º dígito, comparação do número inteiro) | Cliente Evolution único (`apps/whatsapp/evolution.py`), credenciais só no `.env` | API oficial da Meta, transmissões e templates |
| Tratamento `@lid` / `@s.whatsapp.net` / `remoteJidAlt` / `senderPn` | Webhook com segredo, idempotência por `UNIQUE` no banco e por evento | Kanban de SLA com cores e protocolos |
| `fromMe` (mensagens do celular), `pushName` ignorado em `fromMe` | Mídia em pasta privada, servida só com login e permissão, baixada sob demanda | Scripts D0–D15, pedido de armações pelo chat |
| Parser de eventos (temporárias, visualização única, revogação, status, contatos) — corrigido vídeo e figurinha | Permissão checada em toda API (na CDO qualquer usuário logado acessava qualquer conversa por id) | Transcrição de áudio, painel "Dev Evolution" que expunha apikeys |
| Apagar para mim / para todos, prazo de 48 h | Envio síncrono com status "falhou" + Reenviar (na CDO era thread solta) | Assinatura `*Nome*` no topo das mensagens |
| Seletor de emojis (`emoji-picker-element` 1.29.1, Apache-2.0) e `chat-emoji.js` | Tela nova nos tokens do rebranding, mobile first | Token da Meta escrito no código da CDO (recomendo revogar, termina em `…NkZD`) |
| Perfis por vendedora e etiquetas coloridas | Polling leve (3 s / 10 s) só com a aba visível | |

## 2. Integração com clientes, pedidos e cards

- Conversa vinculada automaticamente ao `Cliente` pelo telefone canônico; sem cadastro, o painel lateral oferece "Cadastrar" (cria o cliente com o número da conversa).
- Painel lateral: pedidos do cliente (por `cliente` e por telefone) com etapa, total, pago, saldo, link ativo (copiar), "Abrir pedido", "Link cartão" e envio de arquivos do pedido (arte/nota/comprovante vão como documento, sem compressão).
- Card do Kanban e detalhe do pedido: botões **Conversa** / **Abrir conversa** e **Link cartão** / **Gerar link de pagamento (cartão)**.
- Mensagens automáticas (orçamento, pronto para retirada com "SALDO A PAGAR NA RETIRADA", entregue): novo botão "enviar pelo sistema" ao lado de cada uma. O texto é o mesmo de antes (sem emojis), sai pelo serviço único, entra no histórico do chat marcado como "Automática · pedido #…", registra no histórico do pedido e marca o cliente como avisado. O botão `wa.me` continua como alternativa.
- Número usado para falar com o cliente do pedido: o de quem está agindo → o do responsável do pedido → a instância marcada como "usar nas mensagens automáticas".

## 3. Regra do valor do link (aprovada)

`valor = total_amount − paid_amount` (o `total_amount` já sai do formulário com atacado, desconto por camisa e abatimento; `paid_amount` inclui sinal e pagamentos anteriores). Taxa do cartão **não** repassada (configurável). Até 3x sem juros; 4x em diante com juros Price de 2,99% a.m. pagos pelo cliente; máximo 6x; parcela mínima R$ 50; validade 72 h. Tudo em `Decimal`, `ROUND_HALF_UP`, enviado em centavos.

| Pedido | Já pago | Link | Opções |
|---|---|---|---|
| R$ 300,00 | R$ 50,00 (sinal) | **R$ 250,00** | 1x 250,00 · 2x 125,00 · 3x 83,33 (sem juros) · 4x 67,24 = 268,96 · 5x 54,57 = 272,85 (6x = 46,13 < mínimo, não oferecido) |
| R$ 180,00 | — | R$ 180,00 | 1x, 2x 90,00, 3x 60,00 (4x daria < R$ 50) |
| R$ 100,01 | — | R$ 100,01 (10001 centavos) | 1x 100,01, 2x 50,01 |

O pedido recebe só o saldo (R$ 250,00 no exemplo); juros pagos pelo cliente ficam registrados no link e no histórico.

## 4. Migrações (todas aditivas)

- `whatsapp/0001_initial` — cria `pf_whatsapp_instancias`, `pf_whatsapp_etiquetas`, `pf_whatsapp_conversas`, `pf_whatsapp_mensagens`, `pf_whatsapp_eventos`.
- `payments/0008_linkpagamento` — cria `pf_links_pagamento`.
- `business/0005_…` — adiciona 8 colunas `link_*` com padrão em `pf_business_settings`.

Só `CreateModel`, `AddField`, `AddIndex`, `AddConstraint`. Unicidade feita com colunas anuláveis (o MariaDB ignora `UNIQUE` condicional): "um link ativo por pedido" via `trava_ativo`, "mensagem não duplica" via `(conversa, id_externo)`.

## 5. O que preencher antes de usar

`.env` (modelo em `.env.example`):
- **Umbler Talk (padrão):** `WHATSAPP_PROVEDOR=umbler`, `UMBLER_API_TOKEN`, `UMBLER_ORGANIZATION_ID`, `UMBLER_WEBHOOK_SECRET`, `WHATSAPP_WEBHOOK_BASE_URL` — passo a passo em `umbler.md`. Agendar também `python manage.py whatsapp_atualizar_status` (1–2 min).
- Evolution (alternativa):
- `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_API_VERSION` (2 ou 1)
- `EVOLUTION_WEBHOOK_BASE_URL` (URL pública do Print) e `EVOLUTION_WEBHOOK_SECRET` (segredo aleatório; sem ele o webhook recusa tudo)
- `WHATSAPP_MEDIA_ROOT` (no Docker já é `/app/private_media`, volume `print_fornece_private_media`), `WHATSAPP_MAX_UPLOAD_MB`, `WHATSAPP_REVOGAR_ATE_HORAS`
- Stone: `STONE_SANDBOX_SECRET_KEY` (sk_test_…) / `STONE_PROD_SECRET_KEY` — **obrigatórias agora** (ver 9.1). `STONE_PAYMENT_LINK_API_URL` é opcional.

No sistema:
- **Chat WhatsApp → Números conectados** (admin): cadastrar uma instância por vendedora (+ opcional "Empresa" compartilhada/automáticas), **Conectar** (QR Code), **Configurar webhook**. Ou `python manage.py whatsapp_webhooks --aplicar`.
- **Configurações → Link de pagamento no cartão**: parcelas, sem juros, parcela mínima, juros, repasse de taxa, validade, mensagem padrão.
- Etiquetas: pelo admin do Django (Etiquetas do chat).
- Agendar `python manage.py conciliar_pagamentos` (ex.: a cada 30 min) no cron do servidor.
- No painel do Pagar.me: webhook apontando para `/payments/stone/webhook/` com os eventos `order.paid`, `charge.paid`, `charge.underpaid`, `order.canceled`.

## 6. Cenários testados

| Cenário | Resultado |
|---|---|
| Automatizados — chat (42 testes): webhook texto/mídia/`@lid`/`fromMe`/contato novo/duplicado/origem inválida/instância desconhecida/JSON inválido/erro isolado no lote, eco sem duplicar, revogação recebida, status só avança, vínculo com cliente, notificação única, envio com emoji, falha + reenviar, apagar para mim/todos/fora do prazo/sem permissão, upload privado com limite e tipo, mídia sob demanda, polling, permissões por vendedora/admin/compartilhada/produção, painel, cadastro de cliente, abrir pelo pedido, mensagem automática, arquivo do pedido | **Passou** |
| Automatizados — link (28 testes): cálculo (sem sinal, com sinal, atacado/desconto, taxa, juros, centavos quebrados, sem saldo, cancelado), payload só cartão em centavos, idempotency key, reaproveitar, regenerar quando valor muda, `UNIQUE` de link ativo, valor confirmado divergente, falha na API, permissão, telas, cancelar, signal de mudança no pedido, webhook total/parcial/juros/forjado/de outro link/duplicado, card em "Pagamento confirmado", nota pedida uma vez, envio e confirmação no chat, conciliação, trava de ambiente, webhook Stone antigo endurecido | **Passou** |
| Navegador (servidor isolado com dados fictícios): 1280, 768, 390/375, 360 px; tema escuro e claro; contraste ≥ 4,5:1; emojis; envio; navegação voltar no celular; detalhe do pedido; Kanban; tela do link | **Passou**, console sem erros |
| Real — Evolution de teste (enviar/receber, emojis, mídias, apagar, tempo real) | **Não executado** — sem instância de teste |
| Real — sandbox Pagar.me (gerar, pagar aprovado e recusado, webhook via túnel, expiração, cancelamento) | **Não executado** — sem `sk_test_` |

## 7. Testes, ruff e build

- Suíte completa: **261 testes passaram, 0 falhas** (171 existentes + 42 do chat + 28 do link + 20 da Umbler), em 9 min. Antes das mudanças eram 171 passando.
- `ruff check` nos arquivos alterados: **0 erros** (limpei 28 avisos antigos desses arquivos; restam 3 em arquivos não tocados).
- `manage.py check`: sem problemas. `makemigrations --check`: sem pendências. O projeto não tem etapa de build de front-end (CSS/JS estáticos).

## 8. Como testar

1. Preencher o `.env` (seção 5), `python manage.py migrate`, subir o sistema.
2. Admin → **Chat WhatsApp** → **Números conectados** → cadastrar `pf_teste` (vendedora: você) → **Conectar** → ler o QR com o celular de teste → **Configurar webhook**.
3. Do outro celular de teste, mande "oi 😀" para o número conectado: a conversa aparece em até 10 s, com não lidas e notificação no sino.
4. Responda pelo sistema (Enter envia no computador; no celular, botão de enviar). Teste anexo (imagem, PDF), emoji pelo botão de carinha, apagar (seta no balão).
5. Mande uma mensagem pelo celular conectado: ela aparece como "Pelo celular".
6. Abra um pedido com saldo → **Gerar link de pagamento (cartão)** → confira os valores → **Confirmar** → **Enviar pelo chat** (ou **Copiar link**).
7. No sandbox, pague com o cartão de teste aprovado; o pedido deve ir para "Pagamento confirmado", a nota é pedida, a vendedora recebe notificação e o chat registra "Pagamento recebido". Repita com o cartão recusado (nada muda no pedido).
8. Celular: abra `/chat/` no telefone; a lista e a conversa são telas separadas; o botão voltar do Android volta para a lista; o campo de mensagem fica visível com o teclado aberto.

## 9. Riscos e pendências

1. **Chaves da Stone vazadas no repositório.** A chave secreta (`sk_…36d1`, sem `test_`, provavelmente de produção), a pública (`pk_…pd8G`) e o account id estavam escritos em `config/settings/base.py` (como padrão, inclusive no modo sandbox), no `.env.example` e em um teste. Removi dos três, mas **continuam no histórico do Git: gere chaves novas no painel do Pagar.me**. Antes do deploy, garanta que o `.env` de produção define `STONE_PROD_SECRET_KEY`/`STONE_PROD_PUBLIC_KEY`/`STONE_PROD_ACCOUNT_ID` — sem o valor padrão, a cobrança Stone para se essas variáveis não estiverem lá.
2. **Trava de ambiente:** sandbox agora recusa chave sem `sk_test_`, e produção recusa `sk_test_`.
3. **Mudanças no fluxo de pagamento existente** (necessárias e cobertas por teste de regressão):
   - o webhook da Stone passou a consultar a cobrança/pedido na API antes de dar baixa (antes, um POST forjado marcava o pedido como pago);
   - `reconcile_order_payment` passou a somar ao valor já pago (antes recalculava só pelos `OrderPayment` e apagava o sinal digitado no pedido);
   - a impressão automática da nota em pagamentos via webhook Stone não disparava (o `order.save()` apagava a marcação feita pelo sinal) — corrigido.
4. A assinatura do webhook do Pagar.me continua opcional: a V5 não documenta assinatura, e a proteção real agora é a consulta à API.
5. Testes reais pendentes (Evolution e sandbox): é preciso confirmar no sandbox se o `order_code` do link chega como `code` no pedido do webhook (a documentação não garante; há fallback buscando pelo código).
6. Evolution (Baileys) não é oficial: risco de bloqueio do número com envio em massa — use só para atendimento.
7. O banco local `db.sqlite3` já estava fora de sincronia com as migrações (tabela `pf_order_payments` sem registro da migração); não foi alterado.
8. Polling gera ~1 requisição leve a cada 3 s por usuário com conversa aberta.

## 10. Commits

Branch `feat/chat-whatsapp-link-pagamento`:

- `3a3dd4b` fix(stone): webhook confirma na API, trava de ambiente e conciliação sem perder o sinal
- `136a078` feat: chat de WhatsApp integrado via API da Umbler Talk (Evolution como alternativa)
- `b396770` feat: link de pagamento no cartão com valor calculado e envio pelo chat
- (este) docs: análise, referências, plano e relatório do chat e do link de pagamento

Os testes reais (Umbler com o token da empresa e sandbox do Pagar.me) ficam para depois que as chaves forem preenchidas no `.env`.
