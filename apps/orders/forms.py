from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone

from .models import Order


class BrazilianMoneyField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace("R$", "").replace(" ", "")
            if "," in value:
                value = value.replace(".", "").replace(",", ".")
        return super().to_python(value)


class OrderForm(forms.ModelForm):
    total_amount = BrazilianMoneyField(label="Valor total", max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    paid_amount = BrazilianMoneyField(label="Valor pago", max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, initial=Decimal("0"))

    class Meta:
        model = Order
        fields = [
            "client_name", "client_whatsapp", "description", "total_amount", "payment_status", "paid_amount",
            "payment_method", "due_at", "priority", "responsible", "internal_notes",
        ]
        labels = {
            "client_name": "Nome do cliente", "client_whatsapp": "WhatsApp do cliente", "description": "Descrição detalhada",
            "payment_status": "Situação do pagamento", "payment_method": "Forma de pagamento", "due_at": "Data prevista para entrega",
            "priority": "Prioridade", "responsible": "Responsável", "internal_notes": "Observações internas",
        }
        widgets = {
            "description": forms.Textarea(attrs={"maxlength": 5000}),
            "internal_notes": forms.Textarea(attrs={"maxlength": 5000}),
            "client_whatsapp": forms.TextInput(attrs={"data-whatsapp": "", "inputmode": "numeric", "maxlength": 25}),
            "total_amount": forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
            "paid_amount": forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.actor = user
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = self.fields["responsible"].queryset.filter(is_active=True).order_by("name")
        if user and not user.is_administrator and self.instance.pk:
            # Employees keep the historic ability to work orders, but cannot
            # mutate money or assignment; values are enforced in clean().
            for name in ("total_amount", "payment_status", "paid_amount", "payment_method", "responsible"):
                self.fields[name].disabled = True
        for name in ("total_amount", "paid_amount"):
            value = self.initial.get(name)
            if value is not None and not isinstance(value, str):
                self.initial[name] = f"{Decimal(value):.2f}".replace(".", ",")

    def clean_client_whatsapp(self):
        digits = "".join(char for char in self.cleaned_data["client_whatsapp"] if char.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            raise forms.ValidationError("Informe um WhatsApp válido.")
        return digits

    def clean_due_at(self):
        due_at = self.cleaned_data.get("due_at")
        return due_at

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get("total_amount")
        paid = cleaned.get("paid_amount") or Decimal("0")
        status = cleaned.get("payment_status")
        if total is None or status is None:
            return cleaned
        if status == Order.PaymentStatus.PAID:
            cleaned["paid_amount"] = total
        elif status == Order.PaymentStatus.UNPAID:
            cleaned["paid_amount"] = Decimal("0")
        elif status == Order.PaymentStatus.PARTIAL and not (Decimal("0") < paid < total):
            self.add_error("paid_amount", "Para pagamento parcial, informe um valor maior que zero e menor que o total.")
        elif paid > total:
            self.add_error("paid_amount", "O valor pago não pode superar o valor total.")
        return cleaned


class OrderNoteForm(forms.Form):
    text = forms.CharField(label="Nova observação", min_length=2, max_length=5000, widget=forms.Textarea)


class OrderFilterForm(forms.Form):
    search = forms.CharField(required=False, label="Buscar")
    stage = forms.ChoiceField(required=False, choices=[("", "Todas")] + list(Order.Stage.choices), label="Etapa")
    payment_status = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(Order.PaymentStatus.choices), label="Pagamento")
    priority = forms.ChoiceField(required=False, choices=[("", "Todas")] + list(Order.Priority.choices), label="Prioridade")
    responsible = forms.IntegerField(required=False, min_value=1, label="Responsável")
    order = forms.ChoiceField(required=False, choices=[("oldest", "Mais antigo"), ("newest", "Mais recente")], label="Ordem")
