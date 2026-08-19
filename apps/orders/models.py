from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


def attachment_upload_path(instance: "OrderAttachment", filename: str) -> str:
    """Never retain a client-provided path or executable-looking physical name."""
    extension = Path(filename).suffix.lower()
    token = uuid.uuid4().hex
    return f"order_attachments/{instance.order_id or 'unassigned'}/{token}{extension}"


class Order(models.Model):
    class Shift(models.TextChoices):
        MORNING = "manha", "Manhã"
        AFTERNOON = "tarde", "Tarde"

    class PaymentStatus(models.TextChoices):
        UNPAID = "nao_pago", "Não pago"
        PARTIAL = "parcial", "Parcialmente pago"
        PAID = "pago", "Pago"

    class PaymentMethod(models.TextChoices):
        PIX = "pix", "PIX"
        CARD = "cartao", "Cartão"
        CASH = "dinheiro", "Dinheiro"
        TRANSFER = "transferencia", "Transferência"
        OTHER = "outro", "Outro"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENT = "urgente", "Urgente"

    class Stage(models.TextChoices):
        NEW = "novo", "Novo Pedido"
        AWAITING_PAYMENT = "aguardando_pagamento", "Aguardando Pagamento"
        PAYMENT_CONFIRMED = "pagamento_confirmado", "Pagamento Confirmado"
        PRE_PRESS = "pre_impressao", "Pré-Impressão"
        PRODUCTION = "em_producao", "Em Produção"
        READY = "pronto_retirada", "Pronto pra Retirada"
        DELIVERED = "entregue", "Entregue"
        CANCELLED = "cancelado", "Cancelado"

    number = models.CharField("número", max_length=30, unique=True)
    quote_token = models.CharField("token do orçamento", max_length=64, default=uuid.uuid4, db_index=True, editable=False)
    client_name = models.CharField("nome do cliente", max_length=150)
    client_whatsapp = models.CharField("WhatsApp do cliente", max_length=25)
    description = models.TextField("descrição", blank=True, default="")
    total_amount = models.DecimalField("valor total", max_digits=12, decimal_places=2)
    payment_status = models.CharField(max_length=15, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    paid_amount = models.DecimalField("valor pago", max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, null=True, blank=True)
    payment_confirmed_at = models.DateTimeField("pagamento confirmado em", null=True, blank=True)
    payment_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_order_payments",
    )
    # These values are frozen when a payment becomes paid.  A receipt generated
    # later must reflect the sale, not a subsequently edited customer or amount.
    receipt_client_name = models.CharField("cliente no comprovante", max_length=150, blank=True)
    receipt_seller_name = models.CharField("vendedor no comprovante", max_length=150, blank=True)
    receipt_total_amount = models.DecimalField("total no comprovante", max_digits=12, decimal_places=2, null=True, blank=True)
    receipt_paid_amount = models.DecimalField("valor pago no comprovante", max_digits=12, decimal_places=2, null=True, blank=True)
    receipt_payment_method = models.CharField("forma de pagamento no comprovante", max_length=20, blank=True)
    receipt_generated_at = models.DateTimeField("comprovante gerado em", null=True, blank=True)
    due_at = models.DateTimeField("entrega prevista", null=True, blank=True)
    shift = models.CharField("turno de produção", max_length=10, choices=Shift.choices, default=Shift.MORNING, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    internal_notes = models.TextField("observações internas", blank=True)
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.NEW)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="responsible_orders")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_orders")
    stage_updated_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cancelled_orders")
    cliente = models.ForeignKey("payments.Cliente", on_delete=models.SET_NULL, null=True, blank=True, related_name="pedidos_vinculados", verbose_name="cliente cadastrado")
    is_correction = models.BooleanField("pedido de correção / garantia", default=False)
    correction_reason = models.CharField("motivo da correção / defeito", max_length=255, blank=True, default="")
    discount_advance = models.DecimalField("abatimento / entrada já paga", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pf_orders"
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(fields=["stage"], name="pf_order_stage"),
            models.Index(fields=["payment_status"], name="pf_order_payment"),
            models.Index(fields=["created_at"], name="pf_order_created"),
            models.Index(fields=["responsible"], name="pf_order_responsible"),
            models.Index(fields=["due_at"], name="pf_order_due"),
            models.Index(fields=["shift"], name="pf_order_shift"),
            models.Index(fields=["stage", "due_at"], name="pf_order_stage_due"),
            models.Index(fields=["stage", "stage_updated_at"], name="pf_order_stage_move"),
        ]

    def __str__(self) -> str:
        return f"{self.number} — {self.client_name}"

    @property
    def remaining_amount(self):
        return max(0, self.total_amount - self.paid_amount)

    @property
    def primary_material_label(self) -> str:
        if self.is_correction:
            return "Correção / Defeito"
        items = list(self.items.all())
        if not items:
            desc = (self.description or "").lower()
            if "uv" in desc:
                return "DTF UV"
            if "camisa" in desc or "camiseta" in desc:
                return "Camiseta"
            return "DTF Têxtil"
        first = items[0]
        if first.kind == OrderItem.Kind.PRODUCT or "camisa" in first.material_code.lower():
            return "Camisetas"
        if "uv" in first.material_code.lower() or "uv" in first.material_name.lower():
            return "DTF UV"
        if first.kind == OrderItem.Kind.SERVICE:
            return "Serviço"
        return "DTF Têxtil" if "dtf" in first.material_name.lower() else first.material_name

    @property
    def is_active_stage(self) -> bool:
        return self.stage in {
            self.Stage.NEW,
            self.Stage.AWAITING_PAYMENT,
            self.Stage.PAYMENT_CONFIRMED,
            self.Stage.PRE_PRESS,
            self.Stage.PRODUCTION,
            self.Stage.READY,
        }

    @property
    def is_late(self) -> bool:
        return bool(self.due_at and self.due_at < timezone.now() and self.is_active_stage)

    @property
    def primary_attachment(self) -> OrderAttachment | None:
        attachments = getattr(self, "_prefetched_objects_cache", {}).get("attachments")
        if attachments is not None:
            active = [a for a in attachments if getattr(a, "removed_at", None) is None]
            return active[0] if active else None
        return self.attachments.filter(removed_at__isnull=True).order_by("pk").first()


class OrderAttachment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="attachments")
    original_name = models.CharField("nome original", max_length=255)
    file = models.FileField(upload_to=attachment_upload_path, blank=True)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_order_attachments")
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="removed_order_attachments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_order_attachments"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["order", "removed_at"], name="pf_attachment_active")]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def __str__(self) -> str:
        return self.original_name


class OrderItem(models.Model):
    """Historical item rows used by the calculator and the sales receipt."""

    class Kind(models.TextChoices):
        MATERIAL = "material", "Material / DTF"
        PRODUCT = "produto", "Produto / Camisa"
        SERVICE = "servico", "Serviço Extra"
        ADJUSTMENT = "ajuste", "Ajuste"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    position = models.PositiveSmallIntegerField(default=1)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.MATERIAL)
    material_code = models.CharField(max_length=60)
    material_name = models.CharField(max_length=160)
    category = models.CharField(max_length=100)
    product_color = models.CharField("cor do produto", max_length=40, blank=True)
    product_size = models.CharField("tamanho do produto", max_length=10, blank=True)
    film_width_cm = models.PositiveSmallIntegerField(null=True, blank=True)
    art_width_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    art_height_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    art_quantity = models.PositiveIntegerField(null=True, blank=True)
    items_per_row = models.PositiveIntegerField(null=True, blank=True)
    rows = models.PositiveIntegerField(null=True, blank=True)
    used_length_cm = models.PositiveIntegerField(null=True, blank=True)
    charged_length_cm = models.PositiveIntegerField(null=True, blank=True)
    billing_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    billing_unit = models.CharField(max_length=30)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    pricing_rule = models.CharField(max_length=120)
    calculation_detail = models.CharField(max_length=255, blank=True)
    calculation_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_order_items"
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["order", "created_at"], name="pf_item_order_date")]

    def __str__(self) -> str:
        return f"{self.order.number} - {self.material_name}"


class OrderHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="history")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_history_entries")
    action = models.CharField(max_length=60)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_order_history"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["order", "created_at"], name="pf_history_order_date")]


class OrderNote(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="notes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="order_notes")
    text = models.TextField("texto")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_order_notes"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["order", "created_at"], name="pf_note_order_date")]


class OrderStageHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="stage_history")
    previous_stage = models.CharField(max_length=30, choices=Order.Stage.choices, null=True, blank=True)
    new_stage = models.CharField(max_length=30, choices=Order.Stage.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_stage_changes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_order_stage_history"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["order", "created_at"], name="pf_stage_order_date")]

