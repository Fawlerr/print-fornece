from __future__ import annotations

from decimal import Decimal
from django import forms
from .models import Cliente, ClienteArquivo


class BrazilianMoneyField(forms.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 12)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        val_str = str(value).strip().replace("R$", "").replace(" ", "")
        if not val_str:
            return None
        if "," in val_str:
            val_str = val_str.replace(".", "").replace(",", ".")
        return super().to_python(val_str)


class BrazilianDecimalField(forms.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 12)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        val_str = str(value).strip().replace(" ", "")
        if not val_str:
            return None
        if "," in val_str:
            val_str = val_str.replace(".", "").replace(",", ".")
        return super().to_python(val_str)


class ClienteForm(forms.ModelForm):
    preco_especial_metro = BrazilianMoneyField(label="Preço especial DTF/metro (R$)", required=False, help_text="Deixe em branco para usar o preço padrão da tabela.")
    saldo_credito = BrazilianMoneyField(label="Saldo em conta / créditos (R$)", required=False, initial=Decimal("0.00"))
    metros_saldo = BrazilianDecimalField(label="Saldo em metros (Plano de Volume)", max_digits=10, decimal_places=2, required=False, initial=Decimal("0.00"), help_text="Metros disponíveis no pacote contratado.")

    class Meta:
        model = Cliente
        fields = ["nome", "telefone", "cpf_cnpj", "email", "preco_especial_metro", "saldo_credito", "metros_saldo", "observacoes"]
        labels = {
            "nome": "Nome do Cliente / Empresa",
            "telefone": "WhatsApp / Telefone",
            "cpf_cnpj": "CPF ou CNPJ",
            "email": "E-mail",
            "observacoes": "Observações / Instruções",
        }
        widgets = {
            "telefone": forms.TextInput(attrs={"data-whatsapp": ""}),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }


class ClienteArquivoForm(forms.ModelForm):
    class Meta:
        model = ClienteArquivo
        fields = ["nome", "arquivo"]
        labels = {
            "nome": "Nome / Identificação da Arte",
            "arquivo": "Arquivo (PDF, PNG, TIFF, CDR, AI, PSD, ZIP)",
        }


class AdicionarCreditoForm(forms.Form):
    tipo_pacote = forms.ChoiceField(
        label="Opção de Recarga / Pacote",
        choices=[
            ("pacote_50m", "Plano de Volume 50m (R$ 1.750,00 · R$ 35,00/m)"),
            ("pacote_100m", "Plano de Volume 100m (R$ 3.300,00 · R$ 33,00/m)"),
            ("personalizado", "Valor / Metragem Personalizada"),
        ],
        initial="pacote_50m",
    )
    valor_credito = BrazilianMoneyField(label="Valor em R$ a adicionar ao saldo", initial=Decimal("1750.00"))
    metros_adicionar = forms.DecimalField(label="Metros a adicionar ao pacote", max_digits=10, decimal_places=2, initial=Decimal("50.00"))
