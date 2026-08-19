from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.notifications.services import notify_role, notify_user
from apps.orders.models import Order, OrderHistory, OrderStageHistory
from apps.orders.services import ACTIVE_STAGES, _snapshot_receipt_on_payment, require_order_access


def _stage_label(stage: str) -> str:
    return Order.Stage(stage).label


@transaction.atomic
def move_order_stage(*, order_id: int, new_stage: str, actor, request=None) -> Order:
    order = Order.objects.select_for_update().select_related("responsible").get(pk=order_id)
    require_order_access(actor, order)
    if new_stage not in ACTIVE_STAGES:
        raise ValidationError("Etapa inválida para movimentação.")
    if order.stage not in ACTIVE_STAGES:
        raise ValidationError("Pedido indisponível para movimentação.")
    if order.stage == new_stage:
        return order

    # Sector restrictions:
    if getattr(actor, "is_attendance_sales_only", False) and new_stage in {Order.Stage.PRE_PRESS, Order.Stage.PRODUCTION}:
        raise PermissionDenied("A etapa de produção é restrita à equipe técnica / pré-impressão.")
    if getattr(actor, "is_prepress_production_only", False) and new_stage in {Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT}:
        raise PermissionDenied("A movimentação de etapas comerciais é restrita ao atendimento.")

    previous_stage = order.stage
    order.stage = new_stage
    order.stage_updated_at = timezone.now()
    update_fields = ["stage", "stage_updated_at", "updated_at"]

    # Sincronização automática do status de pagamento em etapas confirmadas
    if new_stage in {Order.Stage.PAYMENT_CONFIRMED, Order.Stage.PRE_PRESS, Order.Stage.PRODUCTION, Order.Stage.READY, Order.Stage.DELIVERED}:
        if order.payment_status == Order.PaymentStatus.UNPAID:
            order.payment_status = Order.PaymentStatus.PAID
            order.paid_amount = order.total_amount
            order.payment_confirmed_at = timezone.now()
            order.payment_confirmed_by = actor
            _snapshot_receipt_on_payment(order, actor)
            update_fields.extend([
                "payment_status", "paid_amount", "payment_confirmed_at", "payment_confirmed_by",
                "receipt_client_name", "receipt_seller_name", "receipt_total_amount",
                "receipt_paid_amount", "receipt_payment_method", "receipt_generated_at"
            ])

    if new_stage == Order.Stage.DELIVERED:
        if not order.finished_at:
            order.finished_at = timezone.now()
            update_fields.append("finished_at")

    order.save(update_fields=list(set(update_fields)))
    message = f"Movido de {_stage_label(previous_stage)} para {_stage_label(new_stage)}"
    OrderStageHistory.objects.create(order=order, previous_stage=previous_stage, new_stage=new_stage, user=actor)
    OrderHistory.objects.create(order=order, user=actor, action="mudanca_etapa", description=message)
    record_audit(actor, "mudanca_etapa", "pedido", order.pk, before={"etapa": previous_stage}, after={"etapa": new_stage}, request=request)
    transaction.on_commit(lambda: _notify_stage_change(order, message))
    return order


def _notify_stage_change(order: Order, message: str) -> None:
    link = f"/production/{order.pk}/"
    notify_role("administrador", "Pedido atualizado", f"{order.number}: {message}", link)
    if order.responsible_id:
        notify_user(order.responsible, "Etapa atualizada", f"{order.number}: {message}", link)


@transaction.atomic
def finish_order(*, order_id: int, actor, request=None) -> Order:
    order = Order.objects.select_for_update().select_related("responsible").get(pk=order_id)
    require_order_access(actor, order)
    if order.stage != Order.Stage.READY:
        raise ValidationError("Somente pedidos prontos podem ser finalizados.")
    order.stage = Order.Stage.DELIVERED
    order.finished_at = timezone.now()
    order.stage_updated_at = timezone.now()
    order.save(update_fields=["stage", "finished_at", "stage_updated_at", "updated_at"])
    OrderStageHistory.objects.create(order=order, previous_stage=Order.Stage.READY, new_stage=Order.Stage.DELIVERED, user=actor)
    OrderHistory.objects.create(order=order, user=actor, action="finalizacao", description="Pedido entregue/finalizado.")
    record_audit(actor, "finalizacao", "pedido", order.pk, before={"etapa": Order.Stage.READY}, after={"etapa": Order.Stage.DELIVERED}, request=request)
    transaction.on_commit(lambda: notify_role("administrador", "Pedido entregue", f"{order.number} foi entregue/finalizado.", f"/production/{order.pk}/"))
    return order


@transaction.atomic
def cancel_order(*, order_id: int, actor, request=None) -> Order:
    order = Order.objects.select_for_update().select_related("responsible").get(pk=order_id)
    require_order_access(actor, order)
    if order.stage == Order.Stage.CANCELLED:
        raise ValidationError("Este pedido já está cancelado.")
    if order.stage in (Order.Stage.DELIVERED, "finalizado"):
        raise ValidationError("Pedidos finalizados não podem ser cancelados.")
    previous_stage = order.stage
    order.stage = Order.Stage.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = actor
    order.stage_updated_at = timezone.now()
    order.save(update_fields=["stage", "cancelled_at", "cancelled_by", "stage_updated_at", "updated_at"])
    OrderStageHistory.objects.create(order=order, previous_stage=previous_stage, new_stage=Order.Stage.CANCELLED, user=actor)
    OrderHistory.objects.create(order=order, user=actor, action="cancelamento", description="Pedido cancelado.")
    record_audit(actor, "cancelamento", "pedido", order.pk, before={"etapa": previous_stage}, after={"etapa": Order.Stage.CANCELLED}, request=request)
    transaction.on_commit(lambda: notify_role("administrador", "Pedido cancelado", f"{order.number} foi cancelado.", f"/production/{order.pk}/"))
    return order


@transaction.atomic
def restore_order(*, order_id: int, actor, request=None) -> Order:
    if not actor.is_administrator:
        raise PermissionDenied("Somente administradores podem restaurar pedidos.")
    order = Order.objects.select_for_update().select_related("responsible").get(pk=order_id)
    if order.stage != Order.Stage.CANCELLED:
        raise ValidationError("Somente pedidos cancelados podem ser restaurados.")
    order.stage = Order.Stage.NEW
    order.cancelled_at = None
    order.cancelled_by = None
    order.stage_updated_at = timezone.now()
    order.save(update_fields=["stage", "cancelled_at", "cancelled_by", "stage_updated_at", "updated_at"])
    OrderStageHistory.objects.create(order=order, previous_stage=Order.Stage.CANCELLED, new_stage=Order.Stage.NEW, user=actor)
    OrderHistory.objects.create(order=order, user=actor, action="restauracao", description="Pedido restaurado para Pedido novo.")
    record_audit(actor, "restauracao", "pedido", order.pk, before={"etapa": Order.Stage.CANCELLED}, after={"etapa": Order.Stage.NEW}, request=request)
    return order

