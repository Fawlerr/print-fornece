# Análise do chat de WhatsApp da Casa das Óticas (origem)

Repositório lido (somente leitura): `../cdo-flow` — remoto `DevDream-tech/casa_das_oticas-flow`, branch `main`, commit `391c79d` (atualizado em 15/11/2026, sem alterações locais).

## 1. Stack e arquivos

Mesma stack do Print Fornece: Python 3.14, Django 6.0.7, MariaDB, templates Django + JS puro, sem websocket.

| Camada | Arquivos | Linhas |
|---|---|---|
| Modelos | `apps/chat/models.py` | 661 |
| Regras de negócio | `apps/chat/services.py` | 1230 |
| Cliente Evolution + Meta + parser de webhook | `apps/chat/meta_api.py` | 1406 |
| Views/API JSON | `apps/chat/views.py` | 1515 |
| Perfis por vendedora | `apps/chat/perfis.py` | 188 |
| Transmissões (Meta) | `broadcast.py`, `broadcast_views.py` | 1043 |
| Comandos | `evolution_webhooks`, `sync_evolution_chats`, `ensure_utf8mb4`, `seed_chat_demo`, `process_broadcasts` | 514 |
| Migrações | `0001`–`0007` | 507 |
| Templates | `templates/chat/workspace.html` (2120), `kanban.html` (951), modais de instância/config | ~5 000 |
| CSS/JS | `chat-wa.css`, `chat.css`, `chat-emoji.js`, `chat-layout.js`, `chat-message-actions.js` | ~1 850 |
| Vendor | `static/vendor/emoji-picker-element`, `sortablejs` | — |
| Testes | `test_chat_evolution_webhook.py` (17), `test_chat_emoji_delete.py` (14), `test_chat_perfis.py` (15), `test_chat_meta.py` (10), `test_chat_broadcast.py` (18) | 74 testes |

## 2. Integração com a Evolution API

- **Versão:** o painel diz "Evolution API v1.8.7", mas o código tenta primeiro o formato v2 (`webhook/set` aninhado) e usa campos da v2.x (`remoteJidAlt`, `senderPn`). Na prática roda em v2. **Versão real precisa ser confirmada no servidor.**
- **Cliente HTTP:** `urllib` com header `apikey`, timeout 7–30 s (`_evolution_request`).
- **Envio:** `POST /message/sendText/{inst}`, `POST /message/sendMedia/{inst}` (base64 ou URL), `POST /message/sendWhatsAppAudio/{inst}` (PTT). Tenta o número com e sem o 9º dígito. Áudio convertido para OGG/Opus via ffmpeg (`imageio-ffmpeg`).
- **Apagar para todos:** `DELETE /chat/deleteMessageForEveryone/{inst}` com `{id, remoteJid, fromMe: true}`. Prazo configurável `CHAT_DELETE_FOR_EVERYONE_MAX_HOURS` (48 h).
- **Mídia recebida:** `POST /chat/getBase64FromMediaMessage/{inst}`, baixada em thread após o commit (o webhook responde antes).
- **Instâncias:** `instance/create`, `connect` (QR base64), `connectionState`, `fetchInstances`, `restart`, `logout`, `delete`.
- **Eventos assinados:** `QRCODE_UPDATED`, `CONNECTION_UPDATE`, `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `MESSAGES_DELETE`, `CONTACTS_UPSERT`, `CHATS_UPSERT`.
- **Parser (`parse_incoming_evolution_webhook`)** trata:
  - `messages.upsert`/`messages.set`: desembrulha `ephemeralMessage`, `viewOnce*`, `documentWithCaptionMessage`; extrai texto, imagem, áudio, documento, vídeo (gravado como imagem — bug), figurinha (só texto "[Figurinha]"), localização, contato, enquete, respostas de botão/lista; ignora reações, grupos, status e canais; tipo desconhecido vira aviso no chat.
  - `protocolMessage` REVOKE, `messages.update` com `DELETED` e `messages.delete` → revogação.
  - `messages.update` → status `SERVER_ACK/DELIVERY_ACK/READ/PLAYED` (e numéricos 2–5).
  - `contacts.*`/`chats.*` → associa LID ↔ telefone e nome, sem criar conversa para cada contato da agenda.
- **Comandos:** `evolution_webhooks` (confere/corrige webhook de todas as instâncias) e `sync_evolution_chats` (importa histórico via `chat/findMessages`).

## 3. Modelos

- `WhatsAppAccount` — canal (provedor `meta`/`evolution`), URL, apikey e instância da Evolution, credenciais Meta, `default_agent` (vendedora dona da instância). **Credenciais gravadas no banco em texto puro, com valores padrão fixos no código.**
- `ChatConversation` — contato (`contact_phone`, `contact_lid`), vendedora (`assigned_agent`), vínculo com `orders.Order` e `payments.Cliente`, status do atendimento (fila/em atendimento/aguardando cliente/finalizado), SLA, não lidas, arquivamento.
- `ChatProtocol` — protocolo de atendimento (abre/fecha).
- `ChatMessage` — direção, tipo, texto, `media_file`, `meta_message_id` (id externo, com índice mas **sem unicidade**), status, nota interna, `remote_jid`, `hidden_at/by` (apagar para mim), `revoked_at/by` (apagar para todos).
- `QuickReplyScript`, `MessageTemplate`, `Broadcast`, `BroadcastRecipient`, `WhatsAppOptOut` — respostas rápidas e transmissões da API oficial da Meta.

## 4. Funcionalidades

- Lista de conversas com busca, filtros (não lidas, arquivadas), contador de não lidas, avatar colorido, hora relativa estilo WhatsApp.
- Perfis por vendedora (estilo WhatsApp Business): gestor vê "Todas" e troca de perfil; vendedora vê as dela + a fila sem dona (`perfis.py`). Etiqueta colorida por vendedora (`apps/accounts/cores.py`).
- Conversa aberta: texto, emojis (`emoji-picker-element` vendorizado, carregado no primeiro clique, insere na posição do cursor), mídia (imagem, áudio gravado no navegador, documento), notas internas, status ✓/✓✓.
- Apagar para mim (oculta para a equipe, mantém no banco) e para todos (revoga na Evolution), "Mensagem apagada" para revogações recebidas.
- Mensagens enviadas pelo celular (`fromMe`) aparecem no sistema; as que saíram pelo painel são reconhecidas pelo id ou pelo texto assinado.
- Kanban de atendimento com SLA por cores, protocolos, transferência entre vendedoras, criação de pedido a partir do chat (específico de óticas).
- Tempo real por **polling** (mensagens a cada 2,5 s; lista lateral e kanban por endpoints próprios).

## 5. Tratamentos que já resolveram problemas (trazer)

- `canonical_phone`: DDI 55 + DDD + 9º dígito sempre presente nos celulares; compara o número inteiro para não misturar DDDs diferentes.
- `resolve_evolution_contact`: `@lid` vs `@s.whatsapp.net`, usando `remoteJidAlt`/`senderPn`; em `fromMe` ignora `senderPn` (é o número da própria vendedora).
- Conversa criada só com LID ganha o telefone quando a Evolution o informa (sem duplicar).
- `pushName` ignorado em `fromMe` (é o nome da vendedora, não do cliente).
- Envio tenta com e sem 9º dígito.
- Webhook processa cada evento isolado (um erro não derruba o lote) e responde 200 mesmo com payload ruim (evita reenvio infinito).
- Idempotência por `meta_message_id` antes de criar a mensagem.

## 6. Dependências, variáveis e permissões

- Pacotes: `imageio-ffmpeg` (áudio), `SpeechRecognition`/`audioop-lts`/`standard-aifc` (transcrição), `pillow-heif`, `anthropic`.
- Variáveis: `EVOLUTION_WEBHOOK_URL`, `CHAT_DELETE_FOR_EVERYONE_MAX_HOURS`, `CHAT_MEDIA_DOWNLOAD_SYNC`, `META_*`.
- Permissões: `LoginRequiredMixin` em tudo; gestor = `is_administrator`/`is_dev`/superuser; telas de instância restritas a `is_dev`.

## 7. Problemas e o que NÃO deve ser trazido

**Segurança (graves):**
1. **Token de acesso da Meta escrito no código** como valor padrão em `services.py:get_default_whatsapp_account` (termina em `…NkZD`). Está no histórico do Git da Casa das Óticas. **Recomendo revogar esse token no painel da Meta.** Também há defaults fixos de apikey da Evolution e verify token. Nada disso será trazido.
2. **Webhook da Evolution sem validação de origem**: qualquer pessoa que descubra a URL pode injetar mensagens falsas.
3. **Webhook loga o payload** (até 500/2000 caracteres com telefone e texto do cliente).
4. **Mídias públicas**: servidas por `django.views.static.serve` em `/media/` sem login.
5. **Sem checagem de dono nas APIs**: `ApiSendMessageView`, `ApiSendMediaView`, `ApiConversationMessagesView` etc. buscam a conversa só pelo id; qualquer usuário logado lê ou envia em qualquer conversa (a restrição por vendedora existe só na listagem).
6. Credenciais de instância gravadas no banco em texto puro e devolvidas ao front (`fetch_all_evolution_instances` retorna `apikey`).

**Robustez:**
- Envio de texto em thread (`threading.Thread`) após o commit: se o processo do Gunicorn reciclar, a mensagem fica "enviada" sem ter saído; falhas viram nota interna.
- `meta_message_id` sem `UNIQUE`: dois webhooks simultâneos podem duplicar a mensagem.
- Vídeo registrado como imagem; figurinha sem mídia; sem limite de tamanho de upload.
- Mensagem enviada recebe a assinatura `*Nome*` no topo (decisão de negócio da CDO).

**Específico da Casa das Óticas (fica de fora):** integração com a Meta Cloud API, transmissões/templates, scripts de cadência D0–D15, criação de pedido de armações a partir do chat, kanban de SLA com cores e protocolos, transcrição de áudio, painel "Dev Evolution Manager" com credenciais expostas, `seed_chat_demo`.
