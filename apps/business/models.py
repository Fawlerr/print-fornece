from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models


def default_shirt_discount_models() -> list[str]:
    """Todos os modelos de camisa do catálogo participam por padrão."""
    from apps.orders.calculator import SHIRTS

    return list(SHIRTS.keys())


def default_business_days() -> list[int]:
    """Segunda (0) a sexta (4)."""
    return [0, 1, 2, 3, 4]


class BusinessSettings(models.Model):
    """Configurações de negócio editáveis pelo administrador (registro único, pk=1).

    Valores de regra (desconto, horário, senha, impressão) vivem aqui, no banco,
    e nunca em código. Toda leitura passa por ``BusinessSettings.load()``.
    """

    class DiscountType(models.TextChoices):
        FIXED = "fixo", "Valor fixo (R$ por camisa)"
        PERCENT = "percentual", "Percentual (% por camisa)"

    # A1 — desconto por camisa (mesmo modelo, cor e tamanho)
    shirt_discount_enabled = models.BooleanField(
        "desconto por camisa ativo",
        default=False,
        help_text="Enquanto o valor não for definido, mantenha desativado.",
    )
    shirt_discount_type = models.CharField(
        "tipo de desconto", max_length=12, choices=DiscountType.choices, default=DiscountType.FIXED
    )
    shirt_discount_value = models.DecimalField(
        "valor do desconto", max_digits=8, decimal_places=2, default=Decimal("0.00"),
        help_text="Em R$ por camisa (valor fixo) ou em % (percentual).",
    )
    shirt_discount_min_quantity = models.PositiveSmallIntegerField(
        "quantidade mínima", default=6,
        help_text="Mínimo de camisas do mesmo modelo, cor e tamanho para ganhar o desconto.",
    )
    shirt_discount_models = models.JSONField(
        "modelos participantes", default=default_shirt_discount_models, blank=True,
    )

    # A3 — horário de funcionamento (padrão: segunda a sexta, 8h às 17h)
    business_days = models.JSONField("dias de funcionamento", default=default_business_days, blank=True)
    business_open_time = models.TimeField("abre às", default=datetime.time(8, 0))
    business_close_time = models.TimeField("fecha às", default=datetime.time(17, 0))

    # A4 — impressão da nota
    auto_print_enabled = models.BooleanField(
        "impressão automática da nota ativa", default=True,
        help_text="Liga/desliga para todo o sistema. Cada computador ainda precisa ser marcado como estação de impressão.",
    )
    receipt_paper_width = models.PositiveSmallIntegerField(
        "largura do papel da nota", choices=[(80, "80 mm (térmica)"), (58, "58 mm (térmica)")], default=80,
    )

    updated_at = models.DateTimeField("atualizado em", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="business_settings_updates", verbose_name="atualizado por",
    )

    class Meta:
        db_table = "pf_business_settings"
        verbose_name = "Configurações do negócio"
        verbose_name_plural = "Configurações do negócio"

    def __str__(self) -> str:
        return "Configurações do negócio"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "BusinessSettings":
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj
