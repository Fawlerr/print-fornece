# Referências — Evolution API

Consultado em 15/11/2026.

## Fontes

- Webhooks v2 (oficial): https://doc.evolution-api.com/v2/en/configuration/webhooks
- Webhooks v1 (oficial): https://doc.evolution-api.com/v1/en/configuration/webhooks
- Apagar para todos v2: https://doc.evolution-api.com/v2/api-reference/chat-controller/delete-message-for-everyone
- Set Webhook v2 (referência): https://atendai-eb1f2775.mintlify.app/v2/api-reference/webhook/set
- Evolution Foundation (docs mais novas): https://docs.evolutionfoundation.com.br/en/evolution-api/configuration/webhooks e https://docs.evolutionfoundation.com.br/en/evolution-api/set-webhook
- Issue sobre `messages.upsert` em mensagens enviadas: https://github.com/evolution-foundation/evolution-api/issues/1340

Observação: as páginas de `doc.evolution-api.com` respondem 404 para leitura automática; o conteúdo foi conferido pelos índices de busca e pelas cópias oficiais em Mintlify / Evolution Foundation. As docs divergem entre versões — **conferir no servidor real antes de codificar** (Swagger da própria instância em `/docs`).

## Pontos que importam para o Print Fornece

| Tema | v1.8.x | v2.x |
|---|---|---|
| Configurar webhook | `POST /webhook/set/{inst}` corpo plano `{enabled, url, webhook_by_events, events}` | corpo `{webhook: {enabled, url, byEvents, base64, headers, events}}` (algumas páginas mostram plano com `webhookByEvents`/`webhookBase64`) |
| Cabeçalhos customizados no webhook | não | `webhook.headers` — usaremos para mandar um segredo próprio e validar a origem |
| Nome do evento no payload | `messages.upsert` | `messages.upsert` (na configuração: `MESSAGES_UPSERT`) |
| Envelope do payload | `event`, `instance`, `data`, `apikey` | `event`, `instance`, `data`, `destination`, `date_time`, `server_url`, `apikey` |
| LID | não existe | `remoteJid` pode vir `…@lid`, com `remoteJidAlt`/`senderPn` trazendo o número |
| Apagar para todos | `DELETE /chat/deleteMessageForEveryone/{inst}` | mesmo endpoint, corpo `{id, remoteJid, fromMe, participant}` |
| Mídia recebida | `POST /chat/getBase64FromMediaMessage/{inst}` | mesmo |
| Envio | `sendText` com `textMessage.text` | `sendText` com `text` na raiz |

Eventos a assinar: `MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `MESSAGES_DELETE`, `CONTACTS_UPSERT`, `CHATS_UPSERT`, `CONNECTION_UPDATE`, `QRCODE_UPDATED`.

## Validação da origem do webhook

A Evolution não assina o payload. Estratégia proposta (defesa em camadas):
1. Segredo próprio (`EVOLUTION_WEBHOOK_SECRET`) enviado pelo `webhook.headers` (v2) **ou** embutido na URL (`/chat/webhook/evolution/<segredo>/`) para v1; comparação com `hmac.compare_digest`.
2. `instance` do payload precisa existir no cadastro de instâncias do Print.
3. Opcional: o campo `apikey` do envelope precisa bater com a chave daquela instância.
