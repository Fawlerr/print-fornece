from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.orders.calculator import SHIRTS

from .models import BusinessSettings


class ShirtDiscountSettingsForm(forms.ModelForm):
    shirt_discount_models = forms.MultipleChoiceField(
        label="Modelos participantes",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[(code, shirt.name) for code, shirt in SHIRTS.items()],
    )

    class Meta:
        model = BusinessSettings
        fields = [
            "shirt_discount_enabled",
            "shirt_discount_type",
            "shirt_discount_value",
            "shirt_discount_min_quantity",
            "shirt_discount_models",
        ]
        widgets = {
            "shirt_discount_value": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01", "min": "0"}),
            "shirt_discount_min_quantity": forms.NumberInput(attrs={"inputmode": "numeric", "min": "2", "step": "1"}),
        }

    def clean_shirt_discount_min_quantity(self):
        value = self.cleaned_data["shirt_discount_min_quantity"]
        if value < 2:
            raise forms.ValidationError("A quantidade mínima deve ser de pelo menos 2 camisas.")
        return value

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("shirt_discount_enabled")
        value = cleaned.get("shirt_discount_value") or Decimal("0")
        kind = cleaned.get("shirt_discount_type")
        if value < 0:
            self.add_error("shirt_discount_value", "O desconto não pode ser negativo.")
        if kind == BusinessSettings.DiscountType.PERCENT and value > 100:
            self.add_error("shirt_discount_value", "O percentual deve ficar entre 0 e 100.")
        if enabled and value <= 0:
            self.add_error("shirt_discount_value", "Defina o valor do desconto antes de ativá-lo.")
        if enabled and not cleaned.get("shirt_discount_models"):
            self.add_error("shirt_discount_models", "Escolha ao menos um modelo de camisa.")
        return cleaned
