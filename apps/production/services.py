from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.notifications.services import notify_role, notify_user
from apps.orders.models import Order, OrderHistory, OrderStageHistory
from apps.orders.services import ACTIVE_STAGES, require_order_access

from .models import CancellationAttempt


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

    if new_stage == Order.Stage.DELIVERED:
        if not order.finished_at:
            order.finished_at = timezone.now()
            update_fields.append("finished_at")

    # Baixa automática de estoque de insumos e consumo de metros quando atinge 'Pronto para retirada' ou 'Entregue'
    if new_stage in {Order.Stage.READY, Order.Stage.DELIVERED}:
        from apps.inventory.services import deduct_order_stock
        deduct_order_stock(order, actor)

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


MAX_CANCEL_ATTEMPTS = 5
CANCEL_LOCKOUT = timedelta(minutes=15)
MIN_REASON_LENGTH = 5
PIN_NOT_CONFIGURED = "O administrador precisa definir a senha de cancelamento."


def _request_ip(request) -> str | None:
    if request is None:
        return None
    return request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR") or None


def _recent_failures(actor) -> list:
    since = timezone.now() - CANCEL_LOCKOUT
    return list(CancellationAttempt.objects.filter(user=actor, success=False, created_at__gte=since).order_by("created_at").values_list("created_at", flat=True))


def cancel_order(*, order_id: int, actor, reason: str = "", pin: str = "", request=None) -> Order:
    """Cancela um pedido (mudança de status, nunca apaga) exigindo a senha de gerente.

    Regras validadas somente no backend (A5):
    - motivo obrigatório;
    - senha de cancelamento configurada pelo administrador (senão, bloqueia);
    - senha correta (comparada com o hash; nunca em texto puro);
    - bloqueio temporário após ``MAX_CANCEL_ATTEMPTS`` erros em ``CANCEL_LOCKOUT``.
    Toda tentativa (certa ou errada) é registrada, fora da transação do cancelamento.
    """
    from apps.business.models import BusinessSettings

    reason = (reason or "").strip()
    order = Order.objects.get(pk=order_id)
    require_order_access(actor, order)
    if order.stage == Order.Stage.CANCELLED:
        raise ValidationError("Este pedido já está cancelado.")
    if order.stage in (Order.Stage.DELIVERED, "finalizado"):
        raise ValidationError("Pedidos finalizados não podem ser cancelados.")
    if len(reason) < MIN_REASON_LENGTH:
        raise ValidationError("Informe o motivo do cancelamento (pelo menos 5 caracteres).")

    config = BusinessSettings.load()
    if not config.has_cancellation_pin:
        raise ValidationError(PIN_NOT_CONFIGURED)

    failures = _recent_failures(actor)
    if len(failures) >= MAX_CANCEL_ATTEMPTS:
        unlock_at = failures[0] + CANCEL_LOCKOUT
        minutes = max(1, int((unlock_at - timezone.now()).total_seconds() // 60) + 1)
        raise ValidationError(f"Muitas tentativas erradas. Tente novamente em {minutes} minuto(s).")

    ip = _request_ip(request)
    if not config.check_cancellation_pin(pin or ""):
        CancellationAttempt.objects.create(order=order, user=actor, ip=ip, success=False)
        record_audit(actor, "cancelamento_senha_incorreta", "pedido", order.pk, request=request)
        remaining = MAX_CANCEL_ATTEMPTS - len(failures) - 1
        if remaining <= 0:
            raise ValidationError(f"Senha de cancelamento incorreta. Cancelamento bloqueado por {int(CANCEL_LOCKOUT.total_seconds() // 60)} minutos.")
        raise ValidationError(f"Senha de cancelamento incorreta. Restam {remaining} tentativa(s).")

    CancellationAttempt.objects.create(order=order, user=actor, ip=ip, success=True)
    return _cancel_order_authorized(order_id=order_id, actor=actor, reason=reason, request=request)


@transaction.atomic
def _cancel_order_authorized(*, order_id: int, actor, reason: str, request=None) -> Order:
    order = Order.objects.select_for_update().select_related("responsible").get(pk=order_id)
    if order.stage == Order.Stage.CANCELLED:
        raise ValidationError("Este pedido já está cancelado.")
    previous_stage = order.stage
    order.stage = Order.Stage.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = actor
    order.cancellation_reason = reason
    order.stage_updated_at = timezone.now()
    order.save(update_fields=["stage", "cancelled_at", "cancelled_by", "cancellation_reason", "stage_updated_at", "updated_at"])
    OrderStageHistory.objects.create(order=order, previous_stage=previous_stage, new_stage=Order.Stage.CANCELLED, user=actor)
    who = getattr(actor, "name", "") or getattr(actor, "email", "")
    OrderHistory.objects.create(
        order=order,
        user=actor,
        action="cancelamento",
        description=f"Pedido cancelado por {who}, autorizado com a senha de gerente. Motivo: {reason}",
    )
    record_audit(
        actor, "cancelamento", "pedido", order.pk,
        before={"etapa": previous_stage},
        after={"etapa": Order.Stage.CANCELLED, "motivo": reason, "autorizacao": "senha de gerente"},
        request=request,
    )
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

