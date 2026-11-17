"""Link de pagamento no cartão de crédito (Pagar.me /paymentlinks).

Regra aprovada (15/11/2026):
- o link cobra o SALDO EM ABERTO do pedido: ``total_amount`` (já com atacado, desconto e abatimento)
  menos ``paid_amount`` (sinal e pagamentos anteriores);
- até ``link_parcelas_sem_juros`` o cliente paga só o saldo; acima disso, juros da tabela Price
  (``link_juros_mensal``) pagos pelo cliente; parcelas abaixo de ``link_parcela_minima`` não são oferecidas;
- taxa do cartão repassada só se ``link_repassar_taxa`` estiver ligado (desligado por padrão).

Todo valor é calculado aqui, no servidor, com Decimal e arredondamento HALF_UP, e enviado em centavos.
O pedido só recebe o saldo quitado; os juros ficam registrados no link.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.business.models import BusinessSettings
from apps.orders.models import Order, OrderHistory

from .models import LinkPagamento, StonePagamento
from .stone.services.payments import reconcile_order_payment, record_event
from .stone.services.stone import StoneAPIError, StoneService, stone_response_summary

logger = logging.getLogger("pagamentos")

CENTAVO = Decimal("0.01")
VALOR_MINIMO = Decimal("1.00")


class LinkErro(Exception):
    """Erro de regra do link, com mensagem pronta para a equipe."""


def _q(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def centavos(valor: Decimal) -> int:
    return int((_q(valor) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def reais(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENTAVO)


def formatar(valor: Decimal) -> str:
    inteiro, _, dec = f"{_q(valor):.2f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{'.'.join(grupos)},{dec}"


@dataclass
class Parcela:
    numero: int
    valor_parcela: Decimal
    total: Decimal
    com_juros: bool

    def como_dict(self) -> dict[str, Any]:
        return {
            "numero": self.numero, "valor_parcela": f"{self.valor_parcela:.2f}", "total": f"{self.total:.2f}",
            "total_centavos": centavos(self.total), "com_juros": self.com_juros,
        }


@dataclass
class Calculo:
    total_pedido: Decimal
    pago: Decimal
    saldo: Decimal
    acrescimo: Decimal
    valor: Decimal
    parcelas: list[Parcela] = field(default_factory=list)

    @property
    def valor_centavos(self) -> int:
        return centavos(self.valor)

    def resumo_parcelas(self) -> str:
        if not self.parcelas:
            return "à vista"
        sem = [p for p in self.parcelas if not p.com_juros]
        com = [p for p in self.parcelas if p.com_juros]
        partes = []
        if sem:
            ultima = sem[-1]
            partes.append(f"até {ultima.numero}x de R$ {formatar(ultima.valor_parcela)} sem juros" if ultima.numero > 1 else "à vista")
        if com:
            ultima = com[-1]
            partes.append(f"ou até {ultima.numero}x com juros (R$ {formatar(ultima.valor_parcela)} por parcela)")
        return " ".join(partes)


def _parcela_price(base: Decimal, taxa_mensal: Decimal, n: int) -> Decimal:
    i = taxa_mensal / Decimal(100)
    if i <= 0:
        return _q(base / n)
    fator = (Decimal(1) + i) ** n
    return _q(base * i * fator / (fator - 1))


def calcular(order: Order, config: BusinessSettings | None = None) -> Calculo:
    config = config or BusinessSettings.load()
    if order.stage == Order.Stage.CANCELLED:
        raise LinkErro("Pedido cancelado não pode receber link de pagamento.")
    total = _q(order.total_amount or Decimal("0"))
    pago = _q(order.paid_amount or Decimal("0"))
    saldo = _q(max(Decimal("0"), total - pago))
    if saldo < VALOR_MINIMO:
        raise LinkErro("Este pedido não tem saldo em aberto para cobrar.")
    acrescimo = _q(saldo * config.link_taxa_percentual / Decimal(100)) if config.link_repassar_taxa else Decimal("0.00")
    valor = saldo + acrescimo

    parcelas: list[Parcela] = []
    maximo = max(1, min(int(config.link_max_parcelas or 1), 12))
    sem_juros = max(1, min(int(config.link_parcelas_sem_juros or 1), maximo))
    minimo = _q(config.link_parcela_minima or Decimal("0"))
    for n in range(1, maximo + 1):
        if n <= sem_juros or config.link_juros_mensal <= 0:
            parcela = _q(valor / n)
            item = Parcela(n, parcela, valor, False)
        else:
            parcela = _parcela_price(valor, config.link_juros_mensal, n)
            item = Parcela(n, parcela, _q(parcela * n), True)
        if n > 1 and item.valor_parcela < minimo:
            break
        parcelas.append(item)
    return Calculo(total, pago, saldo, acrescimo, valor, parcelas)


def _codigo(order: Order) -> str:
    base = re.sub(r"[^A-Za-z0-9-]", "", str(order.number))[:36] or str(order.pk)
    seq = LinkPagamento.objects.filter(order=order).count() + 1
    while True:
        codigo = f"PFL-{base}-{seq}"[:52]
        if not LinkPagamento.objects.filter(order_code=codigo).exists():
            return codigo
        seq += 1


def _payload(order: Order, link: LinkPagamento, calculo: Calculo, horas: int) -> dict[str, Any]:
    return {
        "type": "order",
        "name": f"Pedido {order.number} - Print Fornece"[:64],
        "order_code": link.order_code,
        "expires_in": int(horas) * 60,
        "max_paid_sessions": 1,
        "payment_settings": {
            "accepted_payment_methods": ["credit_card"],
            "statement_descriptor": "PRINTFORNECE",
            "credit_card_settings": {
                "operation_type": "auth_and_capture",
                "installments": [{"number": p.numero, "total": centavos(p.total)} for p in calculo.parcelas],
            },
        },
        "cart_settings": {
            "items": [{
                "name": f"Saldo do pedido {order.number}"[:64],
                "amount": calculo.valor_centavos,
                "default_quantity": 1,
            }],
        },
    }


def _historico(order: Order, usuario, acao: str, descricao: str) -> None:
    OrderHistory.objects.create(order=order, user=usuario, action=acao, description=descricao)


def link_ativo(order: Order) -> LinkPagamento | None:
    return LinkPagamento.objects.filter(order=order, status=LinkPagamento.Status.ATIVO).first()


def pode_gerar(user) -> bool:
    """Administradores e atendimento/vendas. Produção não gera link."""
    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_administrator or user.is_dev or user.is_superuser:
        return True
    return not user.is_prepress_production_only


def pode_cancelar(user, link: LinkPagamento) -> bool:
    if not (user and user.is_authenticated):
        return False
    return bool(user.is_administrator or user.is_dev or user.is_superuser or link.criado_por_id == user.pk)


def _cancelar_na_api(link: LinkPagamento, service: StoneService) -> None:
    if not link.pagarme_link_id:
        return
    try:
        service.cancel_payment_link(link.pagarme_link_id)
    except StoneAPIError as exc:
        # Link já cancelado/expirado do lado do Pagar.me responde erro de validação: não impede o cancelamento local.
        if exc.http_status not in (400, 404, 412, 422):
            raise LinkErro("O Pagar.me não confirmou o cancelamento do link. Tente de novo em instantes.") from exc


def cancelar(link: LinkPagamento, usuario, motivo: str, *, service: StoneService | None = None) -> LinkPagamento:
    if link.status != LinkPagamento.Status.ATIVO:
        raise LinkErro("Só links ativos podem ser cancelados.")
    service = service or StoneService()
    _cancelar_na_api(link, service)
    with transaction.atomic():
        link = LinkPagamento.objects.select_for_update().get(pk=link.pk)
        if link.status != LinkPagamento.Status.ATIVO:
            return link
        link.status = LinkPagamento.Status.CANCELADO
        link.cancelado_em = timezone.now()
        link.cancelado_por = usuario
        link.motivo_cancelamento = (motivo or "")[:160]
        link.save(update_fields=["status", "cancelado_em", "cancelado_por", "motivo_cancelamento"])
        _historico(link.order, usuario, "link_pagamento_cancelado",
                   f"Link de pagamento {link.order_code} (R$ {formatar(link.valor)}) cancelado. Motivo: {link.motivo_cancelamento or 'não informado'}.")
    return link


def gerar(order: Order, usuario, *, valor_confirmado_centavos: int | None = None, service: StoneService | None = None) -> tuple[LinkPagamento, bool]:
    """Gera (ou reaproveita) o link do pedido. Devolve (link, reaproveitado)."""
    if not pode_gerar(usuario):
        raise LinkErro("Você não tem permissão para gerar link de pagamento.")
    service = service or StoneService()
    service.require_server_credentials()
    config = BusinessSettings.load()

    with transaction.atomic():
        # Trava o pedido: dois cliques ou duas pessoas não geram dois links.
        order = Order.objects.select_for_update().get(pk=order.pk)
        calculo = calcular(order, config)
        if valor_confirmado_centavos is not None and valor_confirmado_centavos != calculo.valor_centavos:
            raise LinkErro("O saldo do pedido mudou desde a tela de confirmação. Revise os valores e confirme de novo.")

        anterior = link_ativo(order)
        if anterior and not anterior.expirado and anterior.valor_centavos == calculo.valor_centavos:
            return anterior, True
        if anterior:
            motivo = "Link expirado" if anterior.expirado else "Valor do pedido mudou"
            _cancelar_na_api(anterior, service)
            anterior.status = LinkPagamento.Status.EXPIRADO if anterior.expirado else LinkPagamento.Status.CANCELADO
            anterior.cancelado_em = timezone.now()
            anterior.cancelado_por = usuario
            anterior.motivo_cancelamento = motivo
            anterior.save(update_fields=["status", "cancelado_em", "cancelado_por", "motivo_cancelamento"])
            _historico(order, usuario, "link_pagamento_substituido", f"{motivo}: link {anterior.order_code} desativado.")

        horas = int(config.link_validade_horas or 72)
        link = LinkPagamento.objects.create(
            order=order, order_code=_codigo(order), valor_centavos=calculo.valor_centavos,
            saldo_centavos=centavos(calculo.saldo), acrescimo_centavos=centavos(calculo.acrescimo),
            total_pedido=calculo.total_pedido, pago_antes=calculo.pago,
            parcelas=[p.como_dict() for p in calculo.parcelas], expira_em=timezone.now() + timedelta(hours=horas),
            criado_por=usuario,
        )
        falha: str = ""
        try:
            resposta = service.create_payment_link(_payload(order, link, calculo, horas), idempotency_key=str(link.idempotency_key))
            link.pagarme_link_id = str(resposta.get("id") or "")[:100]
            link.url = str(resposta.get("url") or "")[:500]
            if not link.url.startswith("https://"):
                falha = "O Pagar.me não devolveu a URL do link."
        except StoneAPIError as exc:
            falha = f"O Pagar.me recusou a criação do link: {exc.user_message or 'erro desconhecido'}"
        if falha:
            # Grava a falha (e o eventual cancelamento do link anterior) antes de avisar a equipe.
            link.status = LinkPagamento.Status.FALHOU
            link.erro = falha[:255]
            link.save(update_fields=["pagarme_link_id", "url", "status", "erro"])
            _historico(order, usuario, "link_pagamento_falhou", f"Falha ao gerar link de pagamento: {link.erro}")
        else:
            link.save(update_fields=["pagarme_link_id", "url"])
            _historico(order, usuario, "link_pagamento_gerado",
                       f"Link de pagamento no cartão gerado: R$ {formatar(calculo.valor)} (saldo R$ {formatar(calculo.saldo)}), "
                       f"{calculo.resumo_parcelas()}, válido até {timezone.localtime(link.expira_em):%d/%m/%Y %H:%M}.")
    if falha:
        raise LinkErro(falha)
    return link, False


def mensagem_padrao(link: LinkPagamento) -> str:
    config = BusinessSettings.load()
    calculo_parcelas = [
        Parcela(p["numero"], Decimal(p["valor_parcela"]), Decimal(p["total"]), p["com_juros"]) for p in link.parcelas
    ]
    resumo = Calculo(link.total_pedido, link.pago_antes, link.saldo, reais(link.acrescimo_centavos), link.valor, calculo_parcelas).resumo_parcelas()
    try:
        return config.link_mensagem_padrao.format(
            cliente=link.order.client_name, pedido=link.order.number, valor=formatar(link.valor),
            parcelas=resumo, validade=timezone.localtime(link.expira_em).strftime("%d/%m/%Y às %H:%M"), link=link.url,
        )
    except (KeyError, IndexError, ValueError):
        return f"PRINT FORNECE\nLink para pagamento do pedido #{link.order.number} (R$ {formatar(link.valor)}):\n{link.url}"


def enviar_pelo_chat(link: LinkPagamento, usuario, texto: str, conversa=None):
    from apps.whatsapp import services as chat

    if link.status != LinkPagamento.Status.ATIVO or link.expirado:
        raise LinkErro("Este link não está mais ativo. Gere um novo.")
    texto = (texto or "").strip()
    if link.url not in texto:
        raise LinkErro("A mensagem precisa conter o link de pagamento.")
    if conversa is None:
        conversa = chat.conversa_do_pedido(link.order, usuario)
    if conversa is None:
        raise LinkErro("Nenhum número de WhatsApp conectado para falar com este cliente.")
    msg = chat.enviar_texto(conversa, texto, usuario=usuario, origem=chat.Mensagem.Origem.AUTOMATICA, pedido=link.order)
    if msg.status == chat.Mensagem.Status.FALHOU:
        raise LinkErro(msg.erro or "O WhatsApp não aceitou a mensagem.")
    link.enviado_em = timezone.now()
    link.save(update_fields=["enviado_em"])
    _historico(link.order, usuario, "link_pagamento_enviado", f"Link {link.order_code} enviado ao cliente pelo chat do WhatsApp.")
    return msg


# ---------------------------------------------------------------------------
# Confirmação do pagamento (webhook e conciliação) — sempre com dados consultados na API
# ---------------------------------------------------------------------------

def _cobrancas_pagas(pedido_pagarme: dict[str, Any]) -> list[dict[str, Any]]:
    cobrancas = pedido_pagarme.get("charges")
    pagas = []
    for c in cobrancas if isinstance(cobrancas, list) else []:
        if isinstance(c, dict) and str(c.get("status") or "").lower() in {"paid", "overpaid", "underpaid"}:
            pagas.append(c)
    return pagas


def _avisar_confirmacao(link: LinkPagamento) -> None:
    from apps.notifications.services import notify_user

    order = link.order
    destino = order.responsible or link.criado_por
    if destino:
        notify_user(destino, f"Pagamento do pedido #{order.number} confirmado",
                    f"O cliente pagou R$ {formatar(link.valor_pago or link.valor)} pelo link no cartão.",
                    f"/production/{order.pk}/")
    if not link.enviado_em:
        return
    try:
        from apps.whatsapp import services as chat

        conversa = chat.conversa_do_pedido(order, link.criado_por, criar=False)
        if conversa:
            situacao = "Pedido quitado." if order.payment_status == Order.PaymentStatus.PAID else (
                f"Saldo restante: R$ {formatar(order.remaining_amount)}.")
            chat.enviar_texto(
                conversa,
                f"PRINT FORNECE\nPagamento recebido: R$ {formatar(link.valor_pago or link.valor)} no cartão de crédito, pedido #{order.number}.\n{situacao}\nObrigado!",
                usuario=None, origem=chat.Mensagem.Origem.AUTOMATICA, pedido=order,
            )
    except Exception:
        logger.exception("Falha ao enviar a confirmação do link %s pelo chat", link.order_code)


def registrar_pagamento(link: LinkPagamento, pedido_pagarme: dict[str, Any], *, origem: str) -> LinkPagamento:
    """Aplica um pedido Pagar.me (consultado na API) ao link. Idempotente."""
    if str(pedido_pagarme.get("code") or "") != link.order_code:
        raise LinkErro("O pedido do Pagar.me não pertence a este link.")
    pagas = _cobrancas_pagas(pedido_pagarme)
    if not pagas:
        return link
    cobranca = pagas[0]
    pago_cents = sum(int(c.get("paid_amount") or c.get("amount") or 0) for c in pagas)
    if pago_cents <= 0:
        return link

    with transaction.atomic():
        link = LinkPagamento.objects.select_for_update().select_related("order").get(pk=link.pk)
        if link.status in (LinkPagamento.Status.PAGO, LinkPagamento.Status.PAGO_PARCIAL) and link.pagamento_id:
            return link
        # Juros do parcelamento não entram no pedido: registra no máximo o saldo do link (+ taxa repassada não é receita do pedido).
        base_cents = link.saldo_centavos
        registrado_cents = min(pago_cents, base_cents)
        parcial = pago_cents < link.valor_centavos
        transacao = cobranca.get("last_transaction") if isinstance(cobranca.get("last_transaction"), dict) else {}
        charge_id = str(cobranca.get("id") or "")[:100]
        pagamento = StonePagamento.objects.filter(stone_payment_id=charge_id).first() if charge_id else None
        if pagamento is None:
            try:
                with transaction.atomic():
                    pagamento = StonePagamento.objects.create(
                        order=link.order, cliente=link.order.cliente, cliente_nome=link.order.client_name[:120],
                        stone_payment_id=charge_id, stone_order_id=str(pedido_pagarme.get("id") or "")[:100],
                        stone_transaction_id=str(transacao.get("id") or "")[:100], valor=reais(registrado_cents),
                        metodo=StonePagamento.Metodo.CARTAO, status=StonePagamento.Status.PAID,
                        parcelas=int(transacao.get("installments") or 1), referencia=f"Link {link.order_code} - Pedido #{link.order.number}"[:160],
                        response_data=stone_response_summary(pedido_pagarme),
                        paid_at=parse_datetime(str(cobranca.get("paid_at") or "")) or timezone.now(),
                    )
            except IntegrityError:
                pagamento = StonePagamento.objects.get(stone_payment_id=charge_id)
        link.status = LinkPagamento.Status.PAGO_PARCIAL if parcial else LinkPagamento.Status.PAGO
        link.pago_em = pagamento.paid_at or timezone.now()
        link.valor_pago_centavos = pago_cents
        link.parcelas_pagas = pagamento.parcelas
        link.pagarme_order_id = pagamento.stone_order_id
        link.pagarme_charge_id = charge_id
        link.pagamento = pagamento
        link.save(update_fields=["status", "pago_em", "valor_pago_centavos", "parcelas_pagas", "pagarme_order_id", "pagarme_charge_id", "pagamento"])
        record_event(tipo="link_pagamento_pago", descricao=f"Link {link.order_code} pago ({origem}).", pagamento=pagamento,
                     dados={"valor_cobrado_centavos": pago_cents, "registrado_no_pedido": str(reais(registrado_cents)), "parcial": parcial})
        order = reconcile_order_payment(pagamento, source=f"link_pagamento_{origem}")
        juros = max(0, pago_cents - link.valor_centavos)
        detalhe = f" (inclui R$ {formatar(reais(juros))} de juros do parcelamento, pagos pelo cliente)" if juros else ""
        _historico(link.order, None, "link_pagamento_pago",
                   f"Link {link.order_code} pago: R$ {formatar(reais(pago_cents))} em {pagamento.parcelas}x{detalhe}. "
                   f"Registrado no pedido: R$ {formatar(reais(registrado_cents))}." + (" Pagamento parcial." if parcial else ""))
        if order is not None:
            link.order = order
        transaction.on_commit(lambda: _avisar_confirmacao(LinkPagamento.objects.select_related("order", "criado_por").get(pk=link.pk)))
    return link


def localizar_por_codigo(code: str) -> LinkPagamento | None:
    if not code or not code.startswith("PFL-"):
        return None
    return LinkPagamento.objects.select_related("order").filter(order_code=code).first()


def processar_webhook(link: LinkPagamento, data: dict[str, Any], *, service: StoneService | None = None) -> dict[str, Any]:
    """Webhook de pedido/cobrança de um link: o corpo é só um aviso; o estado vem da API."""
    service = service or StoneService()
    order_data = data.get("order") if isinstance(data.get("order"), dict) else {}
    pagarme_order_id = str(order_data.get("id") or (data.get("id") if str(data.get("id", "")).startswith("or_") else "") or "")
    if pagarme_order_id and not re.fullmatch(r"or_[A-Za-z0-9]{4,64}", pagarme_order_id):
        pagarme_order_id = ""  # id fora do formato: não vai para a URL; busca pelo código do link
    if pagarme_order_id:
        pedido = service.get_order(pagarme_order_id)
    else:
        encontrados = service.list_orders_by_code(link.order_code)
        pedido = next((p for p in encontrados if _cobrancas_pagas(p)), encontrados[0] if encontrados else {})
    if not pedido:
        return {"status": "link_sem_pedido", "link": link.order_code}
    link = registrar_pagamento(link, pedido, origem="webhook")
    return {"status": "success", "link": link.order_code, "link_status": link.status, "order_id": link.order_id}


def conciliar_link(link: LinkPagamento, *, service: StoneService | None = None, aplicar: bool = True) -> str:
    """Usado pelo comando conciliar_pagamentos. Devolve o que aconteceu."""
    service = service or StoneService()
    pedidos = service.list_orders_by_code(link.order_code)
    pago = next((p for p in pedidos if _cobrancas_pagas(p) and str(p.get("code") or "") == link.order_code), None)
    if pago:
        if aplicar:
            registrar_pagamento(link, pago, origem="conciliacao")
        return "pago"
    if link.status == LinkPagamento.Status.ATIVO and link.expira_em <= timezone.now():
        if aplicar:
            try:
                _cancelar_na_api(link, service)
            except LinkErro:
                logger.warning("Não foi possível desativar no Pagar.me o link expirado %s", link.order_code)
            LinkPagamento.objects.filter(pk=link.pk, status=LinkPagamento.Status.ATIVO).update(status=LinkPagamento.Status.EXPIRADO, trava_ativo=None)
            _historico(link.order, None, "link_pagamento_expirado", f"Link {link.order_code} expirou sem pagamento.")
        return "expirado"
    return "sem_alteracao"
