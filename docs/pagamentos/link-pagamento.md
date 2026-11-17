# Link de pagamento — Pagar.me Core v5

Consultado em 15/11/2026.

## Fontes oficiais

- Criar link: https://docs.pagar.me/reference/criar-link
- Obter link: https://docs.pagar.me/reference/obter-link
- Listar links: https://docs.pagar.me/reference/obter-links
- Cancelar link: https://docs.pagar.me/reference/cancelar-um-link-de-pagamento
- Visão geral: https://docs.pagar.me/reference/checkout-link
- Eventos de webhook: https://docs.pagar.me/reference/eventos-de-webhook-1
- Webhooks (guia): https://docs.pagar.me/docs/webhooks
- Índice da documentação: https://docs.pagar.me/llms.txt

## Endpoints

| Ação | Teste (`sk_test_`) | Produção |
|---|---|---|
| Criar | `POST https://sdx-api.pagar.me/core/v5/paymentlinks` | `POST https://api.pagar.me/core/v5/paymentlinks` |
| Consultar | `GET …/paymentlinks/{pl_id}` | idem |
| Cancelar | `PATCH …/paymentlinks/{pl_id}/cancel` (204) | idem |

**Atenção:** o link de pagamento em teste usa o host `sdx-api.pagar.me`, diferente da `STONE_API_BASE_URL` usada hoje para `/orders`. O serviço central terá uma URL própria para links, também separada por ambiente.

## Corpo para "somente cartão de crédito"

```json
{
  "type": "order",
  "name": "Pedido 1234 - Print Fornece",
  "order_code": "PF-1234-L3",
  "expires_in": 4320,
  "max_paid_sessions": 1,
  "payment_settings": {
    "accepted_payment_methods": ["credit_card"],
    "statement_descriptor": "PRINTFORNECE",
    "credit_card_settings": {
      "operation_type": "auth_and_capture",
      "installments": [
        {"number": 1, "total": 25000},
        {"number": 2, "total": 25000},
        {"number": 3, "total": 26200}
      ]
    }
  },
  "cart_settings": {
    "items": [{"name": "Saldo do pedido 1234", "amount": 25000, "default_quantity": 1}]
  },
  "customer_settings": {"customer": {"name": "Cliente", "code": "cliente-42"}}
}
```

- Valores sempre em **centavos** (inteiros).
- `expires_in` em **minutos** (não enviar junto com `expires_at`). Sem nenhum dos dois o link não expira.
- Parcelamento: `installments` (lista explícita `{number, total}` — total já com juros) **ou** `installments_setup` (`max_installments`, `amount`, `interest_type`, `interest_rate`, `free_installments`, `customer_fee` — este último só PSP). Não enviar os dois. A lista explícita deixa o cálculo no nosso backend, que é o que queremos.
- `max_paid_sessions: 1` impede que o mesmo link seja pago duas vezes.
- Não há campo `code` no topo: o vínculo com o pedido é por `order_code` (vira o `code` do pedido Pagar.me gerado no pagamento) e `customer.code`.
- Status do link documentados: `building`, `active` (outros — pago/expirado/cancelado — não estão descritos; mapear pela consulta e testar no sandbox).
- Idempotência: a página não menciona; o serviço central já envia `Idempotency-Key` em todo POST e manteremos isso.

## Como o pagamento chega

O link abre o Checkout Pagar.me; quando o cliente paga, a Pagar.me cria um **pedido (`or_…`) e uma cobrança (`ch_…`)** e dispara os webhooks normais:

- `order.paid`, `order.payment_failed`, `order.canceled`, `order.closed`
- `charge.paid`, `charge.payment_failed`, `charge.underpaid`, `charge.overpaid`, `charge.refunded`, `charge.partial_canceled`, `chargeback.received`
- `checkout.created`, `checkout.closed`, `checkout.canceled`

Não existe evento específico de link. Identificação do pedido do Print: `data.order.code` / `data.code` = nosso `order_code`. **A confirmar no sandbox** se o `order_code` do link é propagado igual para o `code` do pedido gerado — se não for, usar o `payment_link_id` presente no pedido ou consultar `GET /paymentlinks/{id}`.

## Segurança do webhook

A documentação não descreve assinatura de webhook. O endpoint atual do Print aceita `X-Hub-Signature` **só se vier**, e confia nos dados do corpo. Para o link vamos: (1) tratar o corpo só como aviso; (2) **reconsultar o pedido/cobrança na API** com a chave secreta antes de registrar qualquer pagamento; (3) manter a idempotência por id do evento e por cobrança.
