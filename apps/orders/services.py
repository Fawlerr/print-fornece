from __future__ import annotations

import json
import mimetypes
import secrets
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_audit
from apps.notifications.models import Notification
from apps.notifications.services import notify_role, notify_user

from .calculator import CalculatorValidationError, Quote, calculate_quote
from .models import Order, OrderAttachment, OrderHistory, OrderItem, OrderNote, OrderStageHistory

ACTIVE_STAGES = {
    Order.Stage.NEW,
    Order.Stage.AWAITING_PAYMENT,
    Order.Stage.PAYMENT_CONFIRMED,
    Order.Stage.PRE_PRESS,
    Order.Stage.PRODUCTION,
    Order.Stage.READY,
}


def can_access_order(user, order: Order) -> bool:
    """Explicit object permission for the shared production queue.

    The legacy app intentionally exposed every order to every active employee.
    This predicate preserves that workflow while still preventing anonymous or
    inactive-account IDOR access at every route.
    """
    return bool(user and user.is_authenticated and user.is_active and order)


def require_order_access(user, order: Order) -> None:
    if not can_access_order(user, order):
        raise PermissionDenied("Você não tem permissão para acessar este pedido.")


def generate_order_number() -> str:
    return f"PF-{timezone.localtime():%Y%m%d-%H%M%S}-{secrets.randbelow(9000) + 1000}"


def _quote_from_payload(payload) -> Quote | None:
    """Validate browser calculator input against the authoritative backend rules."""
    if not payload:
        return None
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (TypeError, json.JSONDecodeError):
        raise ValidationError("Os dados do orçamento são inválidos. Recalcule antes de salvar.") from None
    if not isinstance(data, dict):
        raise ValidationError("Os dados do orçamento são inválidos. Recalcule antes de salvar.")
    try:
        return calculate_quote(
            material_code=str(data.get("material_code", "")),
            width_cm=data.get("width_cm"),
            height_cm=data.get("height_cm"),
            quantity=data.get("quantity"),
        )
    except CalculatorValidationError as exc:
        raise ValidationError(str(exc)) from None


def _create_order_item_from_quote(order: Order, quote: Quote) -> OrderItem:
    highest_position = OrderItem.objects.filter(order=order).aggregate(value=Max("position"))["value"] or 0
    if quote.pricing_type == "per_meter":
        calculation_detail = f"{quote.film_used_m:.2f}".replace(".", ",") + f" m × R$ {quote.unit_price:.2f}".replace(".", ",")
    else:
        calculation_detail = f"{quote.pricing_rule} · valor fixo R$ {quote.total:.2f}".replace(".", ",")
    return OrderItem.objects.create(
        order=order,
        position=highest_position + 1,
        kind=OrderItem.Kind.MATERIAL,
        material_code=quote.material.code,
        material_name=quote.material.name,
        category=quote.material.category,
        art_width_cm=quote.art_width_cm,
        art_height_cm=quote.art_height_cm,
        film_width_cm=int(quote.material.film_width_cm),
        art_quantity=quote.quantity,
        items_per_row=quote.pieces_per_row,
        rows=quote.rows,
        used_length_cm=int(quote.film_used_cm),
        charged_length_cm=int(quote.film_used_cm),
        billing_quantity=quote.film_used_m,
        billing_unit=quote.material.unit,
        pricing_rule=quote.pricing_rule,
        unit_price=quote.unit_price,
        line_total=quote.total,
        calculation_detail=calculation_detail,
        calculation_snapshot=quote.persisted_snapshot(),
    )


def _create_manual_adjustment_item(order: Order, quote: Quote) -> OrderItem | None:
    """Preserve a deliberate manual total change alongside calculator output.

    The order form intentionally lets an attendant negotiate the final amount.
    Saving the difference as its own historical row keeps the receipt's item
    totals equal to the frozen sale total without altering the calculator row.
    """
    adjustment = (order.total_amount - quote.total).quantize(Decimal("0.01"))
    if adjustment == Decimal("0.00"):
        return None
    highest_position = OrderItem.objects.filter(order=order).aggregate(value=Max("position"))["value"] or 0
    formatted = f"{adjustment:.2f}".replace(".", ",")
    return OrderItem.objects.create(
        order=order,
        position=highest_position + 1,
        kind=OrderItem.Kind.ADJUSTMENT,
        material_code="manual_adjustment",
        material_name="Ajuste manual do valor",
        category="Ajuste",
        billing_quantity=Decimal("1.00"),
        billing_unit="Ajuste",
        pricing_rule="Ajuste manual do valor",
        unit_price=adjustment,
        line_total=adjustment,
        calculation_detail=f"1,00 (Ajuste) X R$ {formatted}",
        calculation_snapshot={
            "source": "manual_total_adjustment",
            "quote_total": str(quote.total),
            "order_total": str(order.total_amount),
            "adjustment": str(adjustment),
        },
    )


def _snapshot_receipt_on_payment(order: Order, actor) -> None:
    """Freeze the sales data used by all future receipt downloads."""
    seller = order.responsible or order.created_by or actor
    seller_name = ""
    if seller is not None:
        seller_name = seller.name or seller.email
    order.payment_confirmed_at = timezone.now()
    order.payment_confirmed_by = actor
    order.receipt_client_name = order.client_name
    order.receipt_seller_name = seller_name
    order.receipt_total_amount = order.total_amount
    order.receipt_paid_amount = order.paid_amount
    order.receipt_payment_method = order.payment_method or ""


def create_order(*, form, actor, files, request=None) -> Order:
    quote = _quote_from_payload(form.cleaned_data.get("calculation_payload"))
    with transaction.atomic():
        order = form.save(commit=False)
        order.number = generate_order_number()
        order.created_by = actor
        order.stage = Order.Stage.NEW
        order.stage_updated_at = timezone.now()
        if order.payment_status == Order.PaymentStatus.PAID:
            _snapshot_receipt_on_payment(order, actor)
        order.save()
        if quote is not None:
            _create_order_item_from_quote(order, quote)
            _create_manual_adjustment_item(order, quote)
        OrderHistory.objects.create(order=order, user=actor, action="criacao", description="Pedido criado.")
        if order.payment_status == Order.PaymentStatus.PAID:
            OrderHistory.objects.create(
                order=order,
                user=actor,
                action="pagamento_confirmado",
                description="Pagamento confirmado; dados do comprovante foram registrados.",
            )
        OrderStageHistory.objects.create(order=order, previous_stage=None, new_stage=Order.Stage.NEW, user=actor)
        save_order_attachments(order, files, actor, request=request)
        record_audit(actor, "criacao", "pedido", order.pk, after={"numero": order.number, "valor_total": str(order.total_amount)}, request=request)
    notify_role("administrador", "Novo pedido", f"{order.number} foi criado por {actor.name}.", f"/production/{order.pk}/")
    notify_role("funcionario", "Novo pedido", f"{order.number} entrou na fila de produção.", f"/production/{order.pk}/")
    if order.responsible_id:
        notify_user(order.responsible, "Pedido atribuído", f"{order.number} foi atribuído a você.", f"/production/{order.pk}/")
    return order


def update_order(*, order: Order, form, actor, files, request=None, previous_state=None) -> Order:
    require_order_access(actor, order)
    previous = previous_state or {
        "payment_status": order.payment_status,
        "paid_amount": str(order.paid_amount),
        "responsible_id": order.responsible_id,
    }
    with transaction.atomic():
        updated = form.save(commit=False)
        payment_just_confirmed = (
            previous["payment_status"] != Order.PaymentStatus.PAID
            and updated.payment_status == Order.PaymentStatus.PAID
        )
        if payment_just_confirmed:
            _snapshot_receipt_on_payment(updated, actor)
        updated.save()
        if payment_just_confirmed:
            OrderHistory.objects.create(
                order=updated,
                user=actor,
                action="pagamento_confirmado",
                description="Pagamento confirmado; dados do comprovante foram registrados.",
            )
        OrderHistory.objects.create(order=updated, user=actor, action="edicao", description="Informações do pedido atualizadas.")
        save_order_attachments(updated, files, actor, request=request)
        record_audit(actor, "edicao", "pedido", updated.pk, before=previous, after={"payment_status": updated.payment_status, "paid_amount": str(updated.paid_amount), "responsible_id": updated.responsible_id}, request=request)
    if previous["payment_status"] != updated.payment_status or previous["paid_amount"] != str(updated.paid_amount):
        notify_role("administrador", "Pagamento atualizado", f"{updated.number} teve seu pagamento atualizado.", f"/production/{updated.pk}/", Notification.Type.FINANCIAL)
    if updated.responsible_id and previous["responsible_id"] != updated.responsible_id:
        notify_user(updated.responsible, "Pedido atribuído", f"{updated.number} foi atribuído a você.", f"/production/{updated.pk}/")
    return updated


def _detect_upload_type(upload) -> str:
    head = upload.read(2048)
    upload.seek(0)
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return "image/webp"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    if head.startswith(b"8BPS"):
        return "image/vnd.adobe.photoshop"
    text_head = head.decode("utf-8", errors="ignore").lstrip().lower()
    if "<svg" in text_head[:1024]:
        return "image/svg+xml"
    if head.startswith(b"%!"):
        return "application/postscript"
    # Do not trust a browser-provided MIME type or a filename extension. Unknown
    # bytes deliberately stay octet-stream and are accepted only for legacy
    # desktop formats that have no portable signature.
    return "application/octet-stream"


ALLOWED_UPLOADS = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
    "svg": {"image/svg+xml"},
    "tiff": {"image/tiff"},
    "zip": {"application/zip"},
    # Desktop design formats do not always have a stable magic number; their
    # extensions are retained from the legacy system but all paths stay private.
    "cdr": {"application/octet-stream", "application/cdr", "application/x-cdr", "image/x-cdr"},
    "ai": {"application/pdf", "application/postscript", "application/octet-stream"},
    "eps": {"application/postscript", "application/octet-stream"},
    "psd": {"image/vnd.adobe.photoshop", "application/octet-stream"},
}


def validate_upload(upload) -> tuple[str, str]:
    original_name = Path(upload.name or "").name
    extension = Path(original_name).suffix.lower().lstrip(".")
    if not original_name or extension not in ALLOWED_UPLOADS:
        raise ValidationError("Tipo de arquivo não permitido.")
    if upload.size < 1 or upload.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError("Arquivo inválido ou maior que o limite permitido.")
    content_type = _detect_upload_type(upload)
    if content_type not in ALLOWED_UPLOADS[extension]:
        raise ValidationError("O conteúdo do arquivo não corresponde à extensão permitida.")
    return original_name, content_type


def save_order_attachments(order: Order, files, actor, request=None) -> int:
    count = 0
    for upload in files:
        original_name, content_type = validate_upload(upload)
        attachment = OrderAttachment(order=order, original_name=original_name, content_type=content_type, size=upload.size, created_by=actor)
        attachment.file.save(original_name, upload, save=False)
        attachment.save()
        count += 1
    if count:
        record_audit(actor, "adicionou_anexo", "pedido", order.pk, after={"quantidade": count}, request=request)
    return count


def remove_attachment(*, attachment: OrderAttachment, actor, request=None) -> None:
    require_order_access(actor, attachment.order)
    if attachment.removed_at:
        raise ValidationError("Este anexo já foi removido.")
    with transaction.atomic():
        attachment.removed_at = timezone.now()
        attachment.removed_by = actor
        attachment.save(update_fields=["removed_at", "removed_by"])
        OrderHistory.objects.create(order=attachment.order, user=actor, action="remocao_anexo", description=f"Anexo removido logicamente: {attachment.original_name}")
        record_audit(actor, "removeu_anexo", "pedido", attachment.order_id, before={"arquivo": attachment.original_name}, after={"arquivo_id": attachment.pk}, request=request)


def add_note(*, order: Order, text: str, actor, request=None) -> OrderNote:
    require_order_access(actor, order)
    with transaction.atomic():
        note = OrderNote.objects.create(order=order, user=actor, text=text)
        OrderHistory.objects.create(order=order, user=actor, action="observacao", description="Observação interna adicionada.")
        record_audit(actor, "adicionou_observacao", "pedido", order.pk, request=request)
    notify_role("administrador", "Nova observação", f"{order.number} recebeu uma observação.", f"/production/{order.pk}/")
    if order.responsible_id:
        notify_user(order.responsible, "Nova observação", f"{order.number} recebeu uma observação.", f"/production/{order.pk}/")
    return note
