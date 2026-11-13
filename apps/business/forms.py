from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.orders.calculator import SHIRTS

from .hours import WEEKDAY_CHOICES
from .models import BusinessSettings


class BusinessHoursSettingsForm(forms.ModelForm):
    business_days = forms.TypedMultipleChoiceField(
        label="Dias de funcionamento",
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        choices=WEEKDAY_CHOICES,
    )

    class Meta:
        model = BusinessSettings
        fields = ["business_days", "business_open_time", "business_close_time"]
        widgets = {
            "business_open_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "business_close_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        cleaned = super().clean()
        opens, closes = cleaned.get("business_open_time"), cleaned.get("business_close_time")
        if opens and closes and opens >= closes:
            self.add_error("business_close_time", "O horário de fechamento deve ser depois da abertura.")
        if not cleaned.get("business_days"):
            self.add_error("business_days", "Escolha ao menos um dia de funcionamento.")
        return cleaned


class CancellationPinForm(forms.Form):
    """Define/troca a senha de gerente para cancelar pedidos (nunca mostra a atual)."""

    new_pin = forms.CharField(
        label="Nova senha de cancelamento",
        min_length=4,
        max_length=32,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
        help_text="De 4 a 32 caracteres. Pode ser só números (PIN).",
    )
    confirm_pin = forms.CharField(
        label="Repita a nova senha",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric"}),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_pin") and cleaned.get("new_pin") != cleaned.get("confirm_pin"):
            self.add_error("confirm_pin", "As senhas não conferem.")
        return cleaned

    def save(self, commit=True):
        self.instance.set_cancellation_pin(self.cleaned_data["new_pin"])
        return self.instance


class ReceiptPrintSettingsForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = ["auto_print_enabled", "receipt_paper_width"]


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
