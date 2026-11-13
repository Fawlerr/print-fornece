from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Order, OrderStageHistory


@receiver(post_save, sender=OrderStageHistory)
def request_receipt_print_on_payment_confirmed(sender, instance: OrderStageHistory, created: bool, **kwargs) -> None:
    """A4: todo pedido que entra em "Pagamento confirmado" pede a impressão da nota.

    Vale para todos os caminhos (Kanban, registrar pagamento, marcar como pago,
    aprovação do cliente já pago e webhook da Stone), porque todos gravam o
    histórico de etapas. A estação de impressão consome esse pedido uma única vez
    (``receipt_auto_printed_at``); se o card sair e voltar, não reimprime sozinho.
    """
    if created and instance.new_stage == Order.Stage.PAYMENT_CONFIRMED:
        Order.objects.filter(pk=instance.order_id).update(receipt_print_requested_at=timezone.now())
