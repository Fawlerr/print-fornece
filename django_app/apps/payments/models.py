from django.db import models

from apps.orders.models import Order


class Charge(models.Model):
    class Type(models.TextChoices):
        PIX = "pix", "PIX"
        CARD = "cartao", "Cartão"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="charges")
    provider = models.CharField(max_length=50, default="stone")
    type = models.CharField(max_length=10, choices=Type.choices)
    external_identifier = models.CharField(max_length=190, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=50, default="pendente")
    pix_copy_paste = models.TextField(blank=True)
    checkout_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pf_charges"
        indexes = [models.Index(fields=["order"], name="pf_charge_order"), models.Index(fields=["external_identifier"], name="pf_charge_external")]

