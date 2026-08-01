from django.conf import settings
from django.db import models


class Expense(models.Model):
    class Category(models.TextChoices):
        MATERIAL = "material", "Material"
        MAINTENANCE = "manutencao", "Manutenção"
        ENERGY = "energia", "Energia"
        EMPLOYEES = "funcionarios", "Funcionários"
        TRANSPORT = "transporte", "Transporte"
        RENT = "aluguel", "Aluguel"
        TAXES = "impostos", "Impostos"
        OTHER = "outros", "Outros"

    class Status(models.TextChoices):
        ACTIVE = "ativa", "Ativa"
        CANCELLED = "cancelada", "Cancelada"

    description = models.CharField("descrição", max_length=180)
    category = models.CharField("categoria", max_length=20, choices=Category.choices)
    amount = models.DecimalField("valor", max_digits=12, decimal_places=2)
    expense_date = models.DateField("data da despesa")
    note = models.TextField("observação", blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_expenses")
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cancelled_expenses")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pf_expenses"
        ordering = ["-expense_date", "-pk"]
        indexes = [
            models.Index(fields=["expense_date", "status"], name="pf_expense_date_stat"),
            models.Index(fields=["status", "expense_date"], name="pf_expense_status_dt"),
            models.Index(fields=["category"], name="pf_expense_category"),
        ]

    def __str__(self) -> str:
        return self.description

