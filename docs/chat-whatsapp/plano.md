# Plano — Chat de WhatsApp e link de pagamento no cartão

Status: **aprovado em 15/11/2026 com todas as recomendações** (inclusive branch + PR em vez de push direto na main). Implementação: ver `relatorio-final.md`.

## 0. Estado de partida

- Print Fornece em `main` atualizado (`5e45258`), árvore limpa, sem backup necessário.
- Suíte de testes: **171 passaram, 0 falhas** (5 min 40 s) antes de qualquer mudança.
- Casa das Óticas: `../cdo-flow` (`DevDream-tech/casa_das_oticas-flow`), em dia com o remoto, apenas lido.

## 1. Descobertas que mudam o escopo

1. **O Print Fornece não envia WhatsApp por API hoje.** As "mensagens automáticas" (orçamento com link de aprovação, pronto para retirada, entregue, confirmação de pagamento) são textos montados em `apps/notifications/whatsapp.py` e abertos pela equipe em links `wa.me`. Para aparecerem no histórico do chat elas precisam passar a sair pela Evolution — ver dúvida 6.
2. **Não existe o comando `conciliar_pagamentos`.** Será criado (links + cobranças Stone pendentes).
3. **Webhook da Stone confia no corpo da requisição**: a assinatura só é conferida se o cabeçalho vier, e o status "pago" é aplicado com os dados recebidos, sem reconsultar a API. Hoje qualquer pessoa com a URL poderia marcar um pedido como pago. Proponho corrigir junto (reconsultar a cobrança na API antes de reconciliar) — ver dúvida 7.
4. **Validação de ambiente pelo prefixo**: `require_server_credentials` aceita qualquer `sk_`; com `STONE_ENVIRONMENT=sandbox` uma chave `sk_live`/produção passaria. Vou endurecer: sandbox exige `sk_test_`, produção recusa `sk_test_`.
5. **Chat da Casa das Óticas tem falhas graves** (detalhes em `analise-origem.md`): token da Meta escrito no código (termina em `…NkZD` — recomendo revogar), webhook sem validação, mídias públicas, APIs sem checagem de dono da conversa. Não trago nada disso; reescrevo essas partes.
6. **Evolution:** a CDO diz v1.8.7 no painel mas usa recursos da v2. Preciso da versão real do servidor que o Print vai usar.

## 2. Estratégia para o chat

**Reaproveitar/adaptar (lógica testada em produção na CDO):**
- Normalização de telefone (`canonical_phone`, variantes com/sem 9º dígito), resolução `@lid`/`@s.whatsapp.net`, tratamento de `fromMe` e `pushName`.
- Parser de eventos da Evolution (upsert/update/delete/contacts/chats, revogação, desembrulho de mensagens temporárias/visualização única), corrigindo vídeo e figurinha.
- Regras de apagar para mim / para todos e prazo de revogação.
- Seletor de emojis (`emoji-picker-element` vendorizado + `chat-emoji.js`), perfis por vendedora e etiquetas coloridas.
- Os 74 testes da CDO como base dos cenários.

**Reescrever nos padrões do Print:**
- **Serviço único de WhatsApp** `apps/whatsapp/` (cliente Evolution + envio): usado pelo chat e pelas mensagens automáticas.
- Credenciais da Evolution só por variável de ambiente (`EVOLUTION_API_URL`, `EVOLUTION_API_KEY`); no banco fica só o nome da instância.
- Webhook: valida segredo (`hmac.compare_digest`) + instância cadastrada, grava o evento cru numa tabela de entrada com id único (idempotência por `UNIQUE`) e responde 200; o processamento roda logo em seguida, isolado por evento, com log sem conteúdo de mensagem.
- Envio síncrono com timeout curto e status `falhou` + botão "reenviar", em vez de thread solta.
- Mídia em diretório privado (`PRIVATE_MEDIA_ROOT`, fora de `/media/`), servida por view com login e checagem de permissão, limite de tamanho (`CHAT_MAX_UPLOAD_MB`, padrão 16) e lista de tipos permitidos.
- Toda API JSON verifica se o usuário pode ver aquela conversa.
- Tempo real por polling leve (mensagens novas a cada 3 s com `?after=<id>`, lista a cada 10 s) — o Print não tem Channels/Redis; adicionar websocket é um projeto à parte.
- Visual nos tokens do rebranding (tema escuro padrão, claro opcional), mobile first.

**Não trazer:** Meta Cloud API, transmissões/templates, scripts D0–D15, kanban de SLA e protocolos, criação de pedido de armações, transcrição de áudio, painel dev com credenciais.

## 3. Novas tabelas (migrações só aditivas)

App novo `apps/whatsapp`:
- `WhatsAppInstancia` — nome da instância, apelido, vendedora (FK `User`, opcional), ativa, estado da conexão, número conectado.
- `Conversa` — instância, telefone canônico, LID, nome, `cliente` (FK `payments.Cliente`), vendedora responsável, não lidas, prévia/hora da última mensagem, arquivada. `UNIQUE(instancia, telefone)` quando há telefone.
- `Mensagem` — conversa, direção, tipo, texto, arquivo privado, mimetype, tamanho, `id_externo` (`UNIQUE` por instância), `remote_jid`, status, remetente (usuário), origem (`chat`, `celular`, `automatica`), pedido relacionado (FK opcional), `ocultada_em/por`, `revogada_em/por`.
- `EventoWebhook` — id do evento/mensagem, instância, tipo, recebido em, processado em, erro (sem corpo com dados pessoais além do necessário para reprocessar, expurgado após 30 dias).
- `Etiqueta` + vínculo conversa↔etiqueta (cores por vendedora).

App `apps/payments` (aditivo):
- `LinkPagamento` — pedido, `pl_id`, URL, `order_code`, valor em centavos, base (saldo) em centavos, acréscimo, parcelas máximas, status (`ativo`, `pago`, `expirado`, `cancelado`, `falhou`), expira em, criado por, cancelado por/em, pago em, `Pagamento` vinculado, chave de idempotência. Restrição: no máximo 1 `ativo` por pedido (`UniqueConstraint` condicional).
- Campos novos em `BusinessSettings`: `link_parcelas_max`, `link_parcela_minima`, `link_parcelas_sem_juros`, `link_juros_mensal`, `link_repassar_taxa`, `link_taxa_percentual`, `link_validade_horas`, `link_mensagem_padrao`.

## 4. Integração com clientes, pedidos e cards

- Ao criar/atualizar conversa: busca `Cliente` por telefone canônico; se não achar, botão "Cadastrar cliente" no painel lateral.
- Painel lateral: pedidos do cliente (por `cliente` e por `client_whatsapp` canônico) com etapa, total, pago, saldo e atalho para o detalhe/card.
- Card do Kanban e detalhe do pedido: botão "Abrir conversa" (abre/cria a conversa do telefone do pedido).
- Mensagens automáticas de pedido passam a ser registradas na conversa com origem `automatica` e pedido vinculado, mantendo o texto sem emojis.

## 5. Link de pagamento — funcionamento

1. Botão "Gerar link de pagamento (cartão)" no detalhe, no card e no painel do chat.
2. Backend calcula (`Decimal`, `ROUND_HALF_UP`, depois centavos): **saldo = `total_amount` − soma de `OrderPayment`** (o `total_amount` já sai do formulário com atacado, desconto por camisa e abatimento aplicados). Recusa se saldo ≤ 0 ou pedido cancelado.
3. Tela de confirmação: total, já pago, saldo, acréscimo, valor final e tabela de parcelas.
4. Cria o link via `StoneService.create_payment_link` (serviço central; `Idempotency-Key`; `max_paid_sessions=1`; só `credit_card`; `order_code = PF-<número>-L<seq>`).
5. Se já existir link ativo: com o mesmo valor, reaproveita; com valor diferente, cancela na API e no sistema e gera outro.
6. Enviar pelo chat (mensagem padrão editável, sem emojis) ou copiar.
7. Webhook `order.paid`/`charge.paid` → localiza o link pelo `order_code` → **reconsulta a cobrança na API** → cria `StonePagamento` e chama o `reconcile_order_payment` existente (idempotente; move para "Pagamento confirmado" e pede a impressão uma vez pelo signal atual) → marca link `pago`, avisa o responsável e registra no chat.
8. Juros cobrados do cliente não entram no pedido como receita do produto: o `OrderPayment` registra o **valor do saldo quitado**; o acréscimo fica em `LinkPagamento` e em observação (evita que o pedido apareça "pago a mais").

**Exemplo (regra recomendada):** pedido R$ 300,00, sinal PIX R$ 50,00 → saldo R$ 250,00 (25000 centavos). Até 3x sem juros: link de R$ 250,00 (3 × R$ 83,33 + ajuste de 1 centavo na primeira). 6x com 2,99% a.m. (Price): parcela ≈ R$ 46,14, total ≈ R$ 276,84 — esses números finais saem do código e serão conferidos nos testes.

## 6. Arquivos

**Novos:** `apps/whatsapp/{models,evolution,telefone,parser,services,permissoes,views,urls,admin}.py`, `apps/whatsapp/management/commands/{whatsapp_webhooks,sincronizar_whatsapp}.py`, `apps/payments/links.py`, `apps/payments/management/commands/conciliar_pagamentos.py`, `templates/whatsapp/*.html`, `static/js/chat*.js`, `static/css/chat.css`, `static/vendor/emoji-picker-element/`, `templates/payments/link_*.html`, testes `tests/test_whatsapp_*.py`, `tests/test_link_pagamento*.py`.

**Alterados:** `config/settings/base.py` (INSTALLED_APPS, variáveis), `config/urls.py`, `.env.example`, `apps/payments/stone/services/stone.py` (link + trava de ambiente), `apps/payments/stone/services/payments.py` e `views.py` (webhook com reconsulta), `apps/business/models.py`/forms/template (configurações do link), `apps/notifications/whatsapp.py` (envio pelo serviço único), templates do card e do detalhe do pedido, `templates/base.html` (menu e notificação).

## 7. Riscos

- Evolution não oficial (Baileys): número da empresa pode ser banido se houver envio em massa; restringir a atendimento.
- Divergência v1/v2 da Evolution nos formatos.
- Correção do webhook da Stone muda um fluxo de pagamento que já está em produção.
- Polling aumenta requisições ao servidor (estimativa: 20 usuários × 1 req/3 s ≈ 7 req/s leves).
- Propagação do `order_code` do link para o pedido Pagar.me não está documentada — validar no sandbox antes de confiar.
- Armazenamento de mídia cresce; definir retenção.

## 8. Dúvidas para sua decisão

1. **Instâncias:** uma instância da empresa ou uma por vendedora? *Recomendo uma por vendedora* (é o que dá a navegação por perfis e o "cada vendedora vê o que é dela"), com uma instância "Empresa" opcional para as mensagens automáticas.
2. **Servidor Evolution:** o mesmo da Casa das Óticas (instâncias separadas) ou outro? Qual a versão? *Recomendo servidor próprio do Print* (falha ou atualização de um não derruba o outro, e a apikey global não é compartilhada). Se for o mesmo, preciso de uma apikey por instância, não a global.
3. **Valor certo no cartão:** *Recomendo (a) saldo em aberto*, sem repassar taxa da maquininha, com **juros do parcelamento por conta do cliente** a partir da 4ª parcela; até **3x sem juros**, máximo **6x**, parcela mínima **R$ 50,00**, juros **2,99% a.m.** (valores editáveis nas configurações). Confirme ou ajuste a regra e os números.
4. **Validade do link:** *Recomendo 72 horas.*
5. **Quem gera link:** *Recomendo administradores e funcionários do setor Atendimento/Vendas; o setor Produção não.* Cancelar link: só quem gerou ou administrador.
6. **Mensagens automáticas pela API:** hoje são abertas em `wa.me` pela equipe. Para entrarem no histórico, devem passar a ser enviadas pela Evolution ao clicar no botão (com o `wa.me` mantido como alternativa se a instância estiver desconectada)? *Recomendo sim.* Envio totalmente automático (sem clique) fica para depois.
7. **Webhook da Stone:** posso endurecer o webhook atual (reconsultar a cobrança na API antes de dar baixa e exigir a assinatura quando o segredo estiver configurado)? *Recomendo sim* — é uma brecha que hoje permite marcar pedido como pago com uma requisição falsa.
8. **Ambientes de teste:** preciso de (a) URL + apikey de uma instância de teste da Evolution e um número de WhatsApp de teste; (b) `sk_test_`/`pk_test_` do Pagar.me com link de pagamento habilitado na conta; (c) autorização para usar `cloudflared` para expor o webhook local. Não encontrei nenhum desses no ambiente.
9. **Retenção de mídia:** guardar para sempre ou apagar arquivos com mais de N meses? *Recomendo 12 meses.*
10. **Commit e push direto na `main`** (como pede a missão) ou em branch com PR? *Recomendo branch + PR*, já que o sistema está em produção — mas sigo a `main` se você confirmar.
