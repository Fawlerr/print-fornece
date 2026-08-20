from decimal import Decimal

from django import forms

from .models import SupplyItem, SupplyMovement


class BrazilianQuantityField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(" ", "")
            if "," in value:
                value = value.replace(".", "").replace(",", ".")
        return super().to_python(value)


class SupplyItemForm(forms.ModelForm):
    quantity = BrazilianQuantityField(
        label="Quantidade inicial",
        min_value=Decimal("0.00"),
        initial=Decimal("0.00"),
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )
    minimum_quantity = BrazilianQuantityField(
        label="Estoque mínimo (Alerta)",
        min_value=Decimal("0.00"),
        initial=Decimal("0.00"),
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )

    class Meta:
        model = SupplyItem
        fields = ["name", "category", "unit", "quantity", "minimum_quantity", "notes"]
        labels = {
            "name": "Nome do Insumo *",
            "category": "Categoria *",
            "unit": "Unidade de Medida *",
            "quantity": "Quantidade em Estoque *",
            "minimum_quantity": "Estoque Mínimo",
            "notes": "Observações",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex: Tinta DTF Têxtil - Branco"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Detalhes sobre fornecedor, código ou lote..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("quantity", "minimum_quantity"):
            val = self.initial.get(name)
            if val is not None and not isinstance(val, str):
                self.initial[name] = f"{Decimal(val):.2f}".replace(".", ",")


class SupplyMovementForm(forms.ModelForm):
    quantity = BrazilianQuantityField(
        label="Quantidade *",
        min_value=Decimal("0.01"),
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "Ex: 5,00"}),
    )

    class Meta:
        model = SupplyMovement
        fields = ["movement_type", "quantity", "description"]
        labels = {
            "movement_type": "Tipo de Movimentação *",
            "quantity": "Quantidade *",
            "description": "Motivo / Justificativa",
        }
        widgets = {
            "description": forms.TextInput(attrs={"placeholder": "Ex: Compra NF 1234, Consumo diário, Ajuste..."}),
        }
