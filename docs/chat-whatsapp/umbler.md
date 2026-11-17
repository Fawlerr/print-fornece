# Umbler Talk — integração do chat

Decisão de 17/11/2026: o Print Fornece usa a **API da Umbler Talk** como provedor padrão do WhatsApp. A Evolution continua no código como alternativa (`provedor = evolution` por número).

## Fontes oficiais (consultadas em 17/11/2026)

- OpenAPI v1 (Swagger): https://app-utalk.umbler.com/api/docs/index.html — especificação em `/api/docs/v1/docs.json`
- Como criar Webhooks: https://help.umbler.com/hc/pt-br/articles/14023563758861-Como-criar-Webhooks
- Manual da API do Talk: https://help.umbler.com/hc/pt-br/articles/21150267515149-Manual-da-API-do-Talk

Observações da própria Umbler: a API está disponível no plano **Enterprise** e é marcada como **Beta** (rotas podem mudar).

## O que o Print usa

| Função | Rota | Observação |
|---|---|---|
| Autenticação | `Authorization: Bearer <token>` | token em account.umbler.com/profile |
| Organização | `GET /v1/members/me/` | o id vai em `UMBLER_ORGANIZATION_ID` |
| Enviar texto | `POST /v1/messages/simplified/` (JSON) | `toPhone`, `fromPhone` (E.164), `organizationId`, `message`, `skipReassign: true`, `contactName` |
| Enviar arquivo | `POST /v1/messages/simplified/` (multipart) | campos `ToPhone`, `FromPhone`, `OrganizationId`, `Message`, `File` |
| Estado da mensagem | `GET /v1/messages/{id}/?organizationId=` | `messageState`: Processing/Submitted/Retrying → enviando; Sent → enviada; Received → entregue; Read/Played → lida; Failed/Error → falhou; Deleted → apagada |
| Apagar | `DELETE /v1/messages/{id}/?organizationId=&deleteForEveryone=true` | |
| Mídia recebida | `GET /v1/messages/{id}/` → `file.url` | baixada sob demanda; nunca pela URL do webhook |
| Canais (números) | `GET /v1/channels/?organizationId=` | `id`, `name`, `phoneNumber`, `state` (`Live` = conectado) |
| Limites | 250 envios / 5 s; 100 consultas / 5 s | |

Telefones sempre em E.164 (`+5584999991234`). Um 200 no envio só quer dizer "na fila": a mensagem fica como "enviando" até o comando de status confirmar.

## Webhook

- Cadastro **no painel da Umbler** (Configurações > Webhooks > Novo webhook), escolhendo os canais e o evento **Message**. A URL aparece em **Chat > Números conectados** (só para administradores): `https://SEU-DOMINIO/chat/webhook/umbler/<UMBLER_WEBHOOK_SECRET>/`.
- Formato: `{"Type": "Message", "EventDate": ..., "EventId": ..., "Payload": {"Type": "Chat", "Content": <BasicChatModel>}}`; a mensagem nova está em `Content.LastMessage`, o cliente em `Content.Contact`, o número da empresa em `Content.Channel`.
- A Umbler não assina o webhook: a origem é validada pelo segredo na URL (`hmac.compare_digest`).
- Resposta precisa sair em menos de 5 s; falhas geram até 2 re-tentativas com o **mesmo `EventId`** (usado como chave de idempotência). Mais de 100 falhas por dia pausam o webhook.
- Ignorados: notas internas (`IsPrivate`), grupos e conversas internas (`ContactType`), reações e eventos que não são `Message`.
- A Umbler **ainda não envia eventos de status** (entregue/lida). Por isso existe `python manage.py whatsapp_atualizar_status` (agendar a cada 1–2 min).

## Como ligar

1. `.env`: `WHATSAPP_PROVEDOR=umbler`, `UMBLER_API_TOKEN`, `UMBLER_ORGANIZATION_ID`, `UMBLER_WEBHOOK_SECRET`, `WHATSAPP_WEBHOOK_BASE_URL`.
2. `python manage.py migrate`.
3. Chat > **Números conectados** > **Importar canais da Umbler**; escolha a vendedora de cada número (e marque o número da empresa como compartilhado / usado nas mensagens automáticas).
4. Copie a URL do webhook e cadastre no painel da Umbler (evento Message, canais desejados).
5. Cron: `whatsapp_atualizar_status` (1–2 min) e `conciliar_pagamentos` (30 min).

## Diferenças em relação à Evolution

- Conexão do número (QR Code) é feita no painel da Umbler, não no Print.
- Contato identificado só por LID (sem número) não recebe resposta pelo Print: a rota simplificada exige telefone.
- Mensagens enviadas pela equipe direto no app da Umbler aparecem no Print como "Fora do sistema (celular ou Umbler)".
