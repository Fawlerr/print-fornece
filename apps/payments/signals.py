"""Link de pagamento desatualizado: se o saldo do pedido muda, o link ativo é desativado (API e sistema)."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.orders.models import Order

logger = logging.getLogger("pagamentos")


@receiver(post_save, sender=Order)
def desativar_link_com_valor_antigo(sender, instance: Order, created: bool, **kwargs) -> None:
    if created:
        return
    from .links import centavos
    from .models import LinkPagamento

    link = LinkPagamento.objects.filter(order_id=instance.pk, status=LinkPagamento.Status.ATIVO).only("pk", "saldo_centavos").first()
    if not link:
        return
    saldo_atual = centavos(instance.remaining_amount)
    if saldo_atual == link.saldo_centavos:
        return

    def _cancelar() -> None:
        from .links import LinkErro, cancelar
        from .stone.services.stone import StoneAPIError

        atual = LinkPagamento.objects.select_related("order").filter(pk=link.pk, status=LinkPagamento.Status.ATIVO).first()
        if not atual:
            return
        motivo = "Pago por outro meio" if saldo_atual == 0 else "Valor do pedido mudou"
        try:
            cancelar(atual, None, motivo)
        except (LinkErro, StoneAPIError):
            # Fica ativo no sistema e o comando conciliar_pagamentos tenta de novo; o pagamento, se vier, ainda é registrado.
            logger.exception("Não foi possível desativar o link %s após mudança de valor do pedido", atual.order_code)

    transaction.on_commit(_cancelar)
