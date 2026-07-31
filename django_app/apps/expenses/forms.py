from django import forms

from apps.orders.forms import BrazilianMoneyField

from .models import Expense


class ExpenseForm(forms.ModelForm):
    amount = BrazilianMoneyField(label="Valor", max_digits=12, decimal_places=2, min_value=0.01)

    class Meta:
        model = Expense
        fields = ["description", "category", "amount", "expense_date", "note"]
        labels = {"description": "Descrição", "category": "Categoria", "expense_date": "Data", "note": "Observação"}
        widgets = {
            "amount": forms.TextInput(attrs={"data-money": "", "inputmode": "decimal"}),
            "expense_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["amount"] = f"{self.instance.amount:.2f}".replace(".", ",")

