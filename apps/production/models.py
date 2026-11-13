from __future__ import annotations

from django.conf import settings
from django.db import models


class CancellationAttempt(models.Model):
    """A5: cada tentativa de cancelar um pedido com a senha de gerente (certa ou errada)."""

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="cancellation_attempts", verbose_name="pedido")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cancellation_attempts", verbose_name="usuário")
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    success = models.BooleanField("senha correta", default=False)
    created_at = models.DateTimeField("data", auto_now_add=True)

    class Meta:
        db_table = "pf_cancellation_attempts"
        ordering = ["-created_at", "-pk"]
        verbose_name = "Tentativa de cancelamento"
        verbose_name_plural = "Tentativas de cancelamento"
        indexes = [models.Index(fields=["user", "success", "created_at"], name="pf_cancel_attempt_user")]

    def __str__(self) -> str:
        return f"{self.order_id} · {'ok' if self.success else 'senha errada'} · {self.created_at:%d/%m/%Y %H:%M}"
