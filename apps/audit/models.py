from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    action = models.CharField("ação", max_length=80)
    entity = models.CharField("entidade", max_length=80)
    entity_id = models.PositiveBigIntegerField("identificador da entidade", null=True, blank=True)
    before = models.JSONField("dados anteriores", null=True, blank=True)
    after = models.JSONField("dados posteriores", null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_audit_events"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["entity", "entity_id", "created_at"], name="pf_audit_entity_time"),
            models.Index(fields=["user", "created_at"], name="pf_audit_user_time"),
        ]

    def __str__(self) -> str:
        return f"{self.entity}:{self.entity_id} {self.action}"

