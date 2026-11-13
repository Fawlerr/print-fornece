"""A4 — regras de impressão da nota (validadas no backend)."""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit

from .models import Order, OrderHistory, OrderPrintLog

# Pedidos que entraram em "Pagamento confirmado" há mais tempo que isso não são
# impressos sozinhos por uma estação recém-ligada (evita imprimir um acúmulo antigo).
QUEUE_WINDOW = timedelta(hours=24)


def auto_print_enabled() -> bool:
    from apps.business.models import BusinessSettings

    return BusinessSettings.load().auto_print_enabled


def pending_auto_print_orders():
    if not auto_print_enabled():
        return Order.objects.none()
    return Order.objects.filter(
        stage=Order.Stage.PAYMENT_CONFIRMED,
        receipt_print_requested_at__isnull=False,
        receipt_print_requested_at__gte=timezone.now() - QUEUE_WINDOW,
        receipt_auto_printed_at__isnull=True,
    ).order_by("receipt_print_requested_at", "pk")


def last_print(order: Order) -> OrderPrintLog | None:
    return order.print_logs.select_related("user").order_by("-created_at", "-pk").first()


def record_print(*, order: Order, actor, source: str, device: str = "", request=None) -> OrderPrintLog:
    """Registra uma impressão (quem, quando, onde) no log, no histórico e na auditoria."""
    device = (device or "")[:60]
    log = OrderPrintLog.objects.create(order=order, user=actor if getattr(actor, "is_authenticated", False) else None, source=source, device=device)
    label = dict(OrderPrintLog.Source.choices).get(source, source)
    who = getattr(actor, "name", "") or getattr(actor, "email", "") or "sistema"
    where = f" ({device})" if device else ""
    OrderHistory.objects.create(order=order, user=log.user, action="impressao_nota", description=f"Nota impressa — {label.lower()} por {who}{where}.")
    record_audit(actor, "impressao_nota", "pedido", order.pk, after={"origem": source, "dispositivo": device}, request=request)
    return log


@transaction.atomic
def claim_auto_print(*, order: Order, actor, device: str = "", request=None) -> bool:
    """Reserva a impressão automática da nota. Só uma estação/tela consegue (atômico).

    Retorna False quando a impressão automática está desligada, quando o pedido não
    pediu impressão ou quando a nota já foi impressa automaticamente antes.
    """
    if not auto_print_enabled():
        return False
    claimed = Order.objects.filter(
        pk=order.pk,
        receipt_print_requested_at__isnull=False,
        receipt_auto_printed_at__isnull=True,
    ).update(receipt_auto_printed_at=timezone.now())
    if not claimed:
        return False
    record_print(order=order, actor=actor, source=OrderPrintLog.Source.AUTOMATIC, device=device, request=request)
    return True
