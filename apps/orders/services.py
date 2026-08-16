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

from .calculator import (
    CalculatorValidationError,
    Quote,
    ShirtQuote,
    ServiceQuote,
    calculate_quote,
    calculate_shirt_quote,
    calculate_service_quote,
)
from .models import Order, OrderAttachment, OrderHistory, OrderItem, OrderNote, OrderStageHistory
from apps.production.capacity import evaluate_order_capacity

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


def _parse_items_from_payload(payload) -> list[Quote | ShirtQuote | ServiceQuote]:
    """Validate and parse browser cart items against authoritative pricing rules."""
    if not payload:
        return []
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (TypeError, json.JSONDecodeError):
        raise ValidationError("Os dados do orçamento são inválidos. Recalcule antes de salvar.") from None

    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            raw_items = data["items"]
        else:
            raw_items = [data]
    elif isinstance(data, list):
        raw_items = data
    else:
        raise ValidationError("Os dados do orçamento são inválidos. Recalcule antes de salvar.")

    calculated_items: list[Quote | ShirtQuote | ServiceQuote] = []
    try:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            mat_code = str(item.get("material_code") or item.get("code") or "")

            if kind == "produto" or mat_code.startswith("camisa_"):
                shirt_code = str(item.get("shirt_code") or mat_code)
                calculated_items.append(
                    calculate_shirt_quote(
                        shirt_code=shirt_code,
                        color=str(item.get("color") or item.get("product_color", "Preta")),
                        size=str(item.get("size") or item.get("product_size", "M")),
                        quantity=item.get("quantity", 1),
                    )
                )
            elif kind == "servico" or mat_code in ("ajuste_preparacao_arquivo", "formato_halftone"):
                service_code = str(item.get("service_code") or mat_code)
                calculated_items.append(
                    calculate_service_quote(
                        service_code=service_code,
                        quantity=item.get("quantity", 1),
                    )
                )
            else:
                # Default DTF Material
                calculated_items.append(
                    calculate_quote(
                        material_code=mat_code or "dtf_textil",
                        width_cm=item.get("width_cm"),
                        height_cm=item.get("height_cm"),
                        quantity=item.get("quantity"),
                    )
                )
    except CalculatorValidationError as exc:
        raise ValidationError(str(exc)) from None

    return calculated_items


def _sync_order_items(order: Order, items: list[Quote | ShirtQuote | ServiceQuote]) -> None:
    if not items:
        return

    OrderItem.objects.filter(order=order).delete()
    total_calc = Decimal("0.00")

    for position, quote in enumerate(items, start=1):
        if isinstance(quote, Quote):
            if quote.pricing_type == "per_meter":
                calc_detail = f"{quote.film_used_m:.2f}".replace(".", ",") + f" m × R$ {quote.unit_price:.2f}".replace(".", ",")
            else:
                calc_detail = f"{quote.pricing_rule} · valor fixo R$ {quote.total:.2f}".replace(".", ",")

            OrderItem.objects.create(
                order=order,
                position=position,
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
                calculation_detail=calc_detail,
                calculation_snapshot=quote.persisted_snapshot(),
            )
            total_calc += quote.total

        elif isinstance(quote, ShirtQuote):
            OrderItem.objects.create(
                order=order,
                position=position,
                kind=OrderItem.Kind.PRODUCT,
                material_code=quote.shirt.code,
                material_name=f"Camisa {quote.shirt.name}",
                category=quote.shirt.category,
                product_color=quote.color,
                product_size=quote.size,
                art_quantity=quote.quantity,
                billing_quantity=Decimal(quote.quantity),
                billing_unit=quote.shirt.unit,
                pricing_rule=quote.pricing_rule,
                unit_price=quote.unit_price,
                line_total=quote.total,
                calculation_detail=f"{quote.quantity} un ({quote.color}, {quote.size}) × R$ {quote.unit_price:.2f}".replace(".", ","),
                calculation_snapshot=quote.persisted_snapshot(),
            )
            total_calc += quote.total

        elif isinstance(quote, ServiceQuote):
            OrderItem.objects.create(
                order=order,
                position=position,
                kind=OrderItem.Kind.SERVICE,
                material_code=quote.service.code,
                material_name=quote.service.name,
                category=quote.service.category,
                art_quantity=quote.quantity,
                billing_quantity=Decimal(quote.quantity),
                billing_unit=quote.service.unit,
                pricing_rule=quote.pricing_rule,
                unit_price=quote.unit_price,
                line_total=quote.total,
                calculation_detail=f"{quote.quantity} un × R$ {quote.unit_price:.2f}".replace(".", ","),
                calculation_snapshot=quote.persisted_snapshot(),
            )
            total_calc += quote.total

    # Check for manual price adjustment
    adjustment = (order.total_amount - total_calc).quantize(Decimal("0.01"))
    if adjustment != Decimal("0.00"):
        formatted = f"{adjustment:.2f}".replace(".", ",")
        OrderItem.objects.create(
            order=order,
            position=len(items) + 1,
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
                "calculated_total": str(total_calc),
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
    payload = form.cleaned_data.get("calculation_payload")
    items = _parse_items_from_payload(payload)

    with transaction.atomic():
        order = form.save(commit=False)
        order.number = generate_order_number()
        order.created_by = actor
        order.stage = Order.Stage.NEW
        order.stage_updated_at = timezone.now()
        if order.payment_status == Order.PaymentStatus.PAID:
            _snapshot_receipt_on_payment(order, actor)
        order.save()

        if items:
            _sync_order_items(order, items)

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

    # Capacity check and notification
    dtf_t_m = sum(i.film_used_m for i in items if isinstance(i, Quote) and i.material.code == "dtf_textil")
    dtf_uv_m = sum(i.film_used_m for i in items if isinstance(i, Quote) and i.material.code == "dtf_uv")
    cap_warnings = evaluate_order_capacity(
        order=order,
        shift=order.shift,
        dtf_textil_meters=dtf_t_m,
        dtf_uv_meters=dtf_uv_m,
    )
    if cap_warnings and request:
        from django.contrib import messages
        for warn in cap_warnings:
            messages.warning(request, f"⚠️ Atenção de Capacidade: {warn}")

    notify_role("administrador", "Novo pedido", f"{order.number} foi criado por {actor.name}.", f"/production/{order.pk}/")
    notify_role("funcionario", "Novo pedido", f"{order.number} entrou na fila de produção.", f"/production/{order.pk}/")
    if order.responsible_id:
        notify_user(order.responsible, "Pedido atribuído", f"{order.number} foi atribuído a você.", f"/production/{order.pk}/")
    return order


def update_order(*, order: Order, form, actor, files, request=None, previous_state=None) -> Order:
    require_order_access(actor, order)
    payload = form.cleaned_data.get("calculation_payload")
    items = _parse_items_from_payload(payload)

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

        if items:
            _sync_order_items(updated, items)

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
