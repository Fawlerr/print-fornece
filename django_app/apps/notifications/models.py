from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        ORDER = "pedido", "Pedido"
        FINANCIAL = "financeiro", "Financeiro"
        SYSTEM = "sistema", "Sistema"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField("título", max_length=160)
    message = models.TextField("mensagem")
    link = models.CharField(max_length=255, blank=True)
    type = models.CharField(max_length=15, choices=Type.choices, default=Type.ORDER)
    read_at = models.DateTimeField("lida em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_notifications"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["user", "read_at", "created_at"], name="pf_notification_read")]

    def __str__(self) -> str:
        return self.title

