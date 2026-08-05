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
    description = models.TextField("descrição")
    total_amount = models.DecimalField("valor total", max_digits=12, decimal_places=2)
    payment_status = models.CharField(max_length=15, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    paid_amount = models.DecimalField("valor pago", max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, null=True, blank=True)
    due_at = models.DateTimeField("entrega prevista", null=True, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    internal_notes = models.TextField("observações internas", blank=True)
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.NEW)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="responsible_orders")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_orders")
    stage_updated_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cancelled_orders")
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
            models.Index(fields=["stage", "due_at"], name="pf_order_stage_due"),
            models.Index(fields=["stage", "stage_updated_at"], name="pf_order_stage_move"),
        ]

    def __str__(self) -> str:
        return f"{self.number} — {self.client_name}"

    @property
    def remaining_amount(self):
        return self.total_amount - self.paid_amount

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

