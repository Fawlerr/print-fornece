from decimal import Decimal

from django.conf import settings
from django.db import models


class SupplyItem(models.Model):
    class Category(models.TextChoices):
        DTF_TEXTIL = "dtf_textil", "DTF Têxtil"
        DTF_UV = "dtf_uv", "DTF UV"
        SHIRTS = "camisas", "Camisetas"
        OTHER = "outros", "Outros Insumos"

    class Unit(models.TextChoices):
        UNIT = "unidade", "Unidade(s)"
        METER = "metro", "Metros (m)"
        ROLL = "rolo", "Rolo(s) / Bobina(s)"
        LITER = "litro", "Litro(s)"
        ML = "ml", "Mililitros (ml)"
        BOTTLE = "frasco", "Frasco(s)"
        KG = "kg", "Quilogramas (kg)"
        PACK = "pacote", "Pacote(s)"

    name = models.CharField("nome do insumo", max_length=150)
    category = models.CharField(
        "categoria",
        max_length=30,
        choices=Category.choices,
        default=Category.DTF_TEXTIL,
        db_index=True,
    )
    unit = models.CharField(
        "unidade de medida",
        max_length=20,
        choices=Unit.choices,
        default=Unit.UNIT,
    )
    quantity = models.DecimalField(
        "quantidade em estoque",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    minimum_quantity = models.DecimalField(
        "estoque mínimo",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Avisar quando o saldo atingir ou ficar abaixo deste valor.",
    )
    notes = models.TextField("observações", blank=True, default="")
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        db_table = "pf_supplies"
        ordering = ["category", "name"]
        verbose_name = "Insumo de Estoque"
        verbose_name_plural = "Insumos de Estoque"
        indexes = [
            models.Index(fields=["category", "name"], name="pf_supplies_cat_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_category_display()})"

    @property
    def is_low_stock(self) -> bool:
        return self.minimum_quantity > 0 and self.quantity <= self.minimum_quantity


class SupplyMovement(models.Model):
    class MovementType(models.TextChoices):
        ENTRY = "entrada", "Entrada (Compra / Reposição)"
        OUTPUT = "saida", "Saída (Consumo / Produção)"
        ADJUSTMENT = "ajuste", "Ajuste / Inventário"

    item = models.ForeignKey(
        SupplyItem,
        on_delete=models.CASCADE,
        related_name="movements",
        verbose_name="insumo",
    )
    movement_type = models.CharField(
        "tipo de movimentação",
        max_length=20,
        choices=MovementType.choices,
        default=MovementType.ENTRY,
    )
    quantity = models.DecimalField(
        "quantidade movimentada",
        max_digits=10,
        decimal_places=2,
    )
    previous_quantity = models.DecimalField(
        "saldo anterior",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    new_quantity = models.DecimalField(
        "novo saldo",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    description = models.CharField("motivo / observação", max_length=255, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supply_movements",
        verbose_name="registrado por",
    )
    created_at = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        db_table = "pf_supply_movements"
        ordering = ["-created_at"]
        verbose_name = "Movimentação de Estoque"
        verbose_name_plural = "Movimentações de Estoque"

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} - {self.item.name} ({self.quantity} {self.item.get_unit_display()})"
