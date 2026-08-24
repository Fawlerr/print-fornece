from datetime import date

from django import forms

from apps.orders.models import Order


class ReportFilterForm(forms.Form):
    start = forms.DateField(label="Data inicial", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Data final", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    stage = forms.ChoiceField(label="Etapa", required=False, choices=[("", "Todas")] + list(Order.Stage.choices))
    payment_status = forms.ChoiceField(label="Pagamento", required=False, choices=[("", "Todos")] + list(Order.PaymentStatus.choices))
    responsible = forms.IntegerField(label="Funcionário", required=False, min_value=1)
    priority = forms.ChoiceField(label="Prioridade", required=False, choices=[("", "Todas")] + list(Order.Priority.choices))

    def initial_for_period(self):
        today = date.today()
        return {"start": today.replace(day=1), "end": today}


class ProductionReportFilterForm(forms.Form):
    month = forms.CharField(label="Mês/Ano", required=False, widget=forms.TextInput(attrs={"type": "month"}))
    responsible = forms.IntegerField(label="Funcionário", required=False, min_value=1)
    material_type = forms.ChoiceField(
        label="Tipo de Material",
        required=False,
        choices=[
            ("", "Todos os Materiais (Têxtil + UV)"),
            ("dtf_textil", "DTF Têxtil"),
            ("dtf_uv", "DTF UV Rígidos"),
        ],
    )
