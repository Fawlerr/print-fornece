from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.notifications.models import Notification
from apps.notifications.services import notify_role, notify_user

from .calculator import (
    CalculatorValidationError,
    Quote,
    ShirtQuote,
    ServiceQuote,
    apply_shirt_volume_discount,
    brl,
    calculate_quote,
    calculate_shirt_quote,
    calculate_service_quote,
    shirt_calculation_detail,
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
    """Generate a 4-digit sequential order number (e.g., '0001', '0042')."""
    import re
    orders_with_numbers = Order.objects.values_list("number", flat=True)
    highest_num = 0
    for num_str in orders_with_numbers:
        if num_str:
            clean_str = re.sub(r"[^\d]", "", num_str)
            if clean_str.isdigit():
                val = int(clean_str)
                # Ignore timestamp-like legacy numbers (e.g. 20260816...)
                if val < 1000000 and val > highest_num:
                    highest_num = val

    next_num = highest_num + 1
    while Order.objects.filter(number=f"{next_num:04d}").exists():
        next_num += 1

    return f"{next_num:04d}"


def _parse_items_from_payload(payload, cliente=None) -> list[Quote | ShirtQuote | ServiceQuote]:
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

    custom_price_fallback = getattr(cliente, "preco_especial_metro", None)

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
            elif kind == "servico" or mat_code in ("ajuste_preparacao_arquivo", "formato_halftone", "servico_avulso", "item_avulso", "avulso"):
                service_code = str(item.get("service_code") or mat_code)
                custom_name = str(item.get("name") or item.get("material_name") or "")
                custom_price = item.get("unit_price") or item.get("custom_price") or item.get("price")
                calculated_items.append(
                    calculate_service_quote(
                        service_code=service_code,
                        quantity=item.get("quantity", 1),
                        custom_name=custom_name,
                        custom_price=custom_price,
                    )
                )
            else:
                # Default DTF Material
                material_code = mat_code or "dtf_textil"
                if "uv" in material_code.lower():
                    custom_price = item.get("custom_price_per_meter") or getattr(cliente, "preco_especial_dtf_uv", None) or custom_price_fallback
                else:
                    custom_price = item.get("custom_price_per_meter") or custom_price_fallback
                calculated_items.append(
                    calculate_quote(
                        material_code=material_code,
                        width_cm=item.get("width_cm") or item.get("art_width_cm"),
                        height_cm=item.get("height_cm") or item.get("art_height_cm"),
                        quantity=item.get("quantity") or item.get("art_quantity"),
                        custom_price_per_meter=custom_price,
                    )
                )
    except CalculatorValidationError as exc:
        raise ValidationError(str(exc)) from None

    return calculated_items


def price_cart(payload, cliente=None) -> tuple[list[Quote | ShirtQuote | ServiceQuote], list[dict]]:
    """Recalcula o carrinho inteiro no backend com as regras vigentes.

    Fonte da verdade para preços: o navegador só exibe. Inclui o desconto por
    camisa configurado pelo administrador.
    """
    from apps.business.services import shirt_discount_rule

    items = _parse_items_from_payload(payload, cliente=cliente)
    return apply_shirt_volume_discount(items, shirt_discount_rule())


def _normalize_decimal(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except Exception:
        return str(value)


def _quote_signature(quote: Quote | ShirtQuote | ServiceQuote) -> tuple:
    if isinstance(quote, Quote):
        return ("material", quote.material.code, _normalize_decimal(quote.art_width_cm), _normalize_decimal(quote.art_height_cm), quote.quantity)
    if isinstance(quote, ShirtQuote):
        return ("produto", quote.shirt.code, quote.color, quote.size, quote.quantity)
    custom = quote.service.code == "item_avulso"
    return (
        "servico",
        quote.service.code,
        quote.service.name if custom else "",
        _normalize_decimal(quote.unit_price) if custom else "",
        quote.quantity,
    )


def _order_item_signature(item: OrderItem) -> tuple:
    if item.kind == OrderItem.Kind.MATERIAL:
        return ("material", item.material_code, _normalize_decimal(item.art_width_cm), _normalize_decimal(item.art_height_cm), item.art_quantity)
    if item.kind == OrderItem.Kind.PRODUCT:
        return ("produto", item.material_code, item.product_color, item.product_size, item.art_quantity)
    custom = item.material_code == "item_avulso"
    return (
        "servico",
        item.material_code,
        item.material_name if custom else "",
        _normalize_decimal(item.unit_price) if custom else "",
        item.art_quantity,
    )


def order_items_unchanged(order: Order, items: list[Quote | ShirtQuote | ServiceQuote]) -> bool:
    """True quando o carrinho enviado é igual aos itens já gravados no pedido.

    Nesse caso os preços originais são preservados (o pedido não é recalculado
    com as regras vigentes). Qualquer mudança de quantidade, tamanho, cor,
    modelo, medida ou inclusão/remoção de item conta como alteração.
    """
    stored = [
        _order_item_signature(item)
        for item in order.items.exclude(kind=OrderItem.Kind.ADJUSTMENT)
    ]
    sent = [_quote_signature(quote) for quote in items]
    return sorted(map(repr, stored)) == sorted(map(repr, sent))


def _sync_adjustment_item(order: Order, calculated_total: Decimal, position: int) -> None:
    """Mantém o item de ajuste manual coerente com o total informado no pedido."""
    OrderItem.objects.filter(order=order, kind=OrderItem.Kind.ADJUSTMENT).delete()
    adjustment = (order.total_amount - calculated_total).quantize(Decimal("0.01"))
    if adjustment == Decimal("0.00"):
        return
    formatted = f"{adjustment:.2f}".replace(".", ",")
    OrderItem.objects.create(
        order=order,
        position=position,
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
            "calculated_total": str(calculated_total),
            "order_total": str(order.total_amount),
            "adjustment": str(adjustment),
        },
    )


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
                pricing_rule=quote.pricing_rule[:120],
                unit_price=quote.unit_price,
                line_total=quote.total,
                discount_per_unit=quote.discount_per_unit,
                discount_total=quote.discount_total,
                calculation_detail=shirt_calculation_detail(quote)[:255],
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
    _sync_adjustment_item(order, total_calc, position=len(items) + 1)


def _record_shirt_discount(order: Order, items, actor, request=None) -> None:
    """Registra no histórico e na auditoria o desconto por camisa aplicado."""
    discounted = [q for q in items if isinstance(q, ShirtQuote) and q.discount_total > 0]
    if not discounted:
        return
    total = sum((q.discount_total for q in discounted), Decimal("0.00"))
    parts = "; ".join(
        f"{q.quantity}× Camisa {q.shirt.name} {q.color} {q.size}: -{brl(q.discount_per_unit)}/camisa"
        for q in discounted
    )
    OrderHistory.objects.create(
        order=order,
        user=actor,
        action="desconto_camisa",
        description=f"Desconto por camisa aplicado ({parts}). Total de desconto: {brl(total)}.",
    )
    record_audit(actor, "desconto_camisa", "pedido", order.pk, after={"desconto_total": str(total)}, request=request)


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
    cliente = form.cleaned_data.get("cliente")
    items, _hints = price_cart(payload, cliente=cliente)

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

        # Abatimento de saldo do Plano de Volume / Crédito do cliente se aplicável
        if order.cliente:
            dtf_m = sum(i.film_used_m for i in items if isinstance(i, Quote))
            if dtf_m == Decimal("0.00"):
                dtf_m = sum(
                    Decimal(str(it.billing_quantity))
                    for it in order.items.filter(kind=OrderItem.Kind.MATERIAL)
                    if "metro" in (it.billing_unit or "").lower()
                )
            if dtf_m > Decimal("0.00") and order.cliente.metros_saldo and order.cliente.metros_saldo > Decimal("0.00"):
                order.cliente.metros_saldo = max(Decimal("0.00"), order.cliente.metros_saldo - Decimal(str(dtf_m)))

            if order.payment_method == "saldo_credito" or (order.cliente.saldo_credito and order.cliente.saldo_credito >= order.total_amount):
                if order.total_amount > Decimal("0.00"):
                    order.cliente.saldo_credito = max(Decimal("0.00"), order.cliente.saldo_credito - order.total_amount)

            order.cliente.save(update_fields=["saldo_credito", "metros_saldo", "updated_at"])

        desc_criacao = f"Pedido criado.{' (Correção por Defeito)' if order.is_correction else ''}"
        OrderHistory.objects.create(order=order, user=actor, action="criacao", description=desc_criacao)
        _record_shirt_discount(order, items, actor, request=request)
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
    cliente = form.cleaned_data.get("cliente") if hasattr(form, "cleaned_data") else getattr(order, "cliente", None)
    items, _hints = price_cart(payload, cliente=cliente)
    # Preserva os preços originais quando nada mudou nos itens (A1, decisão 6).
    items_preserved = bool(items) and order_items_unchanged(order, items)

    previous = previous_state or {
        "payment_status": order.payment_status,
        "paid_amount": str(order.paid_amount),
        "responsible_id": order.responsible_id,
    }
    with transaction.atomic():
        updated = form.save(commit=False)
        if updated.total_amount and updated.paid_amount:
            if updated.paid_amount < updated.total_amount:
                if updated.paid_amount > Decimal("0.00"):
                    updated.payment_status = Order.PaymentStatus.PARTIAL
                else:
                    updated.payment_status = Order.PaymentStatus.UNPAID
            elif updated.paid_amount >= updated.total_amount and updated.total_amount > Decimal("0.00"):
                updated.payment_status = Order.PaymentStatus.PAID

        payment_just_confirmed = (
            previous["payment_status"] != Order.PaymentStatus.PAID
            and updated.payment_status == Order.PaymentStatus.PAID
        )
        if payment_just_confirmed:
            _snapshot_receipt_on_payment(updated, actor)
        updated.save()

        # Sincroniza parcela única de OrderPayment se a forma de pagamento for alterada no formulário
        if updated.payment_method and updated.payment_method != Order.PaymentMethod.MULTIPLE:
            splits = list(updated.payments.all())
            if len(splits) == 1:
                single_split = splits[0]
                dirty = False
                if single_split.payment_method != updated.payment_method:
                    single_split.payment_method = updated.payment_method
                    dirty = True
                if updated.paid_amount and single_split.amount != updated.paid_amount:
                    single_split.amount = updated.paid_amount
                    dirty = True
                if dirty:
                    single_split.save(update_fields=["payment_method", "amount"])

        if items_preserved:
            kept = list(updated.items.exclude(kind=OrderItem.Kind.ADJUSTMENT))
            kept_total = sum((item.line_total for item in kept), Decimal("0.00"))
            _sync_adjustment_item(updated, kept_total, position=len(kept) + 1)
        elif items:
            _sync_order_items(updated, items)
            _record_shirt_discount(updated, items, actor, request=request)

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
    if head.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")):
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
    "tif": {"image/tiff", "image/x-tiff", "application/octet-stream"},
    "tiff": {"image/tiff", "image/x-tiff", "application/octet-stream"},
    "zip": {"application/zip"},
    # Desktop design formats do not always have a stable magic number; their
    # extensions are retained from the legacy system but all paths stay private.
    "cdr": {"application/octet-stream", "application/cdr", "application/x-cdr", "image/x-cdr"},
    "ai": {"application/pdf", "application/postscript", "application/octet-stream"},
    "eps": {"application/postscript", "application/octet-stream"},
    "psd": {"image/vnd.adobe.photoshop", "application/octet-stream"},
}


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        gb = size / (1024 * 1024 * 1024)
        return f"{gb:.1f} GB".replace(".0 GB", " GB")
    if size >= 1024 * 1024:
        mb = size / (1024 * 1024)
        return f"{mb:.1f} MB".replace(".0 MB", " MB")
    if size >= 1024:
        kb = size / 1024
        return f"{kb:.1f} KB".replace(".0 KB", " KB")
    return f"{size} B"


def validate_upload(upload) -> tuple[str, str]:
    original_name = Path(upload.name or "").name
    extension = Path(original_name).suffix.lower().lstrip(".")
    if not original_name or extension not in ALLOWED_UPLOADS:
        raise ValidationError("Tipo de arquivo não permitido.")
    if upload.size < 1:
        raise ValidationError("Arquivo vazio ou inválido.")
    if upload.size > settings.MAX_UPLOAD_BYTES:
        max_str = _format_bytes(settings.MAX_UPLOAD_BYTES)
        raise ValidationError(f"O arquivo '{original_name}' excede o limite máximo permitido de {max_str}.")
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


def remove_attachment(*, attachment: OrderAttachment, actor, reason: str = "", request=None) -> None:
    require_order_access(actor, attachment.order)
    if attachment.removed_at:
        raise ValidationError("Este anexo já foi removido.")
    with transaction.atomic():
        attachment.removed_at = timezone.now()
        attachment.removed_by = actor
        attachment.removal_reason = reason or ""
        attachment.save(update_fields=["removed_at", "removed_by", "removal_reason"])
        desc = f"Anexo removido logicamente: {attachment.original_name}"
        if reason:
            desc += f" (Motivo: {reason})"
        OrderHistory.objects.create(order=attachment.order, user=actor, action="remocao_anexo", description=desc)
        record_audit(actor, "removeu_anexo", "pedido", attachment.order_id, before={"arquivo": attachment.original_name}, after={"arquivo_id": attachment.pk, "motivo": reason}, request=request)


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
