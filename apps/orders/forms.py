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
    total_amount = BrazilianMoneyField(
        label="Valor total",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
    )
    paid_amount = BrazilianMoneyField(
        label="Valor pago",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        initial=Decimal("0"),
        widget=forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
    )
    discount_advance = BrazilianMoneyField(
        label="Abatimento / Entrada de Preparação (R$)",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        initial=Decimal("0"),
        widget=forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
        help_text="Informe o valor da montagem/preparação já pago antecipadamente para abater do total.",
    )
    calculation_payload = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Order
        fields = [
            "cliente", "client_name", "client_whatsapp", "description", "total_amount", "payment_status", "paid_amount",
            "discount_advance", "is_correction", "correction_reason", "payment_method", "due_at", "shift", "priority", "responsible", "internal_notes",
        ]
        labels = {
            "cliente": "Cliente Cadastrado", "client_name": "Nome do cliente", "client_whatsapp": "WhatsApp do cliente", "description": "Descrição detalhada",
            "is_correction": "Pedido de Correção / Reposição por Defeito (R$ 0,00)", "correction_reason": "Motivo da Correção / Defeito",
            "payment_status": "Situação do pagamento", "payment_method": "Forma de pagamento", "due_at": "Data prevista para entrega",
            "shift": "Turno de produção", "priority": "Prioridade", "responsible": "Responsável", "internal_notes": "Observações internas",
        }
        widgets = {
            "description": forms.Textarea(attrs={"maxlength": 5000}),
            "internal_notes": forms.Textarea(attrs={"maxlength": 5000}),
            "client_whatsapp": forms.TextInput(attrs={"data-whatsapp": "", "inputmode": "numeric", "maxlength": 25}),
            "total_amount": forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
            "paid_amount": forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
            "discount_advance": forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.actor = user
        super().__init__(*args, **kwargs)
        from apps.payments.models import Cliente
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nome")
        self.fields["cliente"].required = False
        self.fields["responsible"].queryset = self.fields["responsible"].queryset.filter(is_active=True).order_by("name")
        self.fields["shift"].required = False
        for name in ("total_amount", "paid_amount", "discount_advance"):
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

    def clean_shift(self):
        shift = self.cleaned_data.get("shift")
        return shift or Order.Shift.MORNING

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("shift"):
            cleaned["shift"] = Order.Shift.MORNING

        # Pedido de correção por defeito: valor total zerado
        if cleaned.get("is_correction"):
            cleaned["total_amount"] = Decimal("0.00")
            cleaned["paid_amount"] = Decimal("0.00")
            cleaned["payment_status"] = Order.PaymentStatus.PAID
            return cleaned

        total = cleaned.get("total_amount")
        paid = cleaned.get("paid_amount") or Decimal("0")
        status = cleaned.get("payment_status")
        if total is None or status is None:
            return cleaned
        if status == Order.PaymentStatus.PAID:
            cleaned["paid_amount"] = total
        elif status == Order.PaymentStatus.UNPAID:
            cleaned["paid_amount"] = Decimal("0")
        elif status == Order.PaymentStatus.PARTIAL:
            if paid >= total and total > Decimal("0"):
                cleaned["payment_status"] = Order.PaymentStatus.PAID
                cleaned["paid_amount"] = total
            elif paid <= Decimal("0"):
                self.add_error("paid_amount", "Para pagamento parcial, informe um valor maior que zero e menor que o total.")
        elif paid > total:
            self.add_error("paid_amount", "O valor pago não pode superar o valor total.")
        return cleaned


class QuickPaymentForm(forms.Form):
    paid_amount = BrazilianMoneyField(
        label="Valor do Pagamento (R$)",
        min_value=Decimal("0.01"),
        widget=forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
    )
    payment_method = forms.ChoiceField(
        label="Forma de Pagamento",
        choices=Order.PaymentMethod.choices,
        initial=Order.PaymentMethod.PIX,
    )
    notes = forms.CharField(
        label="Observação do Pagamento",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex: Entrada de 50%, pago via PIX..."}),
    )


class OrderNoteForm(forms.Form):
    text = forms.CharField(label="Nova observação", min_length=2, max_length=5000, widget=forms.Textarea)


class OrderFilterForm(forms.Form):
    search = forms.CharField(required=False, label="Buscar")
    stage = forms.ChoiceField(required=False, choices=[("", "Todas")] + list(Order.Stage.choices), label="Etapa")
    payment_status = forms.ChoiceField(required=False, choices=[("", "Todos")] + list(Order.PaymentStatus.choices), label="Pagamento")
    priority = forms.ChoiceField(required=False, choices=[("", "Todas")] + list(Order.Priority.choices), label="Prioridade")
    responsible = forms.IntegerField(required=False, min_value=1, label="Responsável")
    order = forms.ChoiceField(required=False, choices=[("oldest", "Mais antigo"), ("newest", "Mais recente")], label="Ordem")
