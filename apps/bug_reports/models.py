from django.conf import settings
from django.db import models


class BugReport(models.Model):
    class Status(models.TextChoices):
        PENDING = "pendente", "Pendente de análise pelo Dev"
        VERIFIED = "verificado", "Verificado"
        FIXED = "corrigido", "Corrigido"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bug_reports",
        verbose_name="usuário",
    )
    description = models.TextField("relato do problema")
    screenshot = models.ImageField(
        "print / captura de tela",
        upload_to="bug_reports/%Y/%m/",
        null=True,
        blank=True,
    )
    current_url = models.CharField("tela / rota onde ocorreu", max_length=500, blank=True)
    status = models.CharField(
        "situação",
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    dev_notes = models.TextField("anotações técnicas do Dev", blank=True)
    resolved_at = models.DateTimeField("resolvido em", null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        db_table = "pf_bug_reports"
        ordering = ["-created_at"]
        verbose_name = "Relato de Bug"
        verbose_name_plural = "Relatos de Bugs"
        indexes = [
            models.Index(fields=["status", "created_at"], name="pf_bug_status_created"),
            models.Index(fields=["user", "created_at"], name="pf_bug_user_created"),
        ]

    def __str__(self) -> str:
        return f"Bug #{self.pk} ({self.get_status_display()}) - {self.user.name or self.user.email}"
