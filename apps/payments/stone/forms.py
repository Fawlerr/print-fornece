"""Forms para o módulo Stone / Pagar.me V5 (Sandbox)."""
from __future__ import annotations

import uuid
from django import forms
from django.core.exceptions import ValidationError

from apps.payments.models import (
    Cliente,
    StoneMetodoPagamento as MetodoPagamento,
    StonePagamento as Pagamento,
)
from .services.normalizers import normalize_phone, parse_brl, validate_document


class StoneClienteForm(forms.ModelForm):
    cpf_cnpj = forms.CharField(max_length=20, label="CPF/CNPJ")
    telefone = forms.CharField(max_length=30, label="Telefone")

    class Meta:
        model = Cliente
        fields = ["nome", "cpf_cnpj", "telefone", "email"]
        widgets = {
            "nome": forms.TextInput(attrs={"autocomplete": "name", "class": "form-control"}),
            "cpf_cnpj": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off", "class": "form-control"}),
            "telefone": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel", "class": "form-control"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "class": "form-control"}),
        }

    def clean_nome(self) -> str:
        name = " ".join(self.cleaned_data["nome"].split())
        if len(name) < 3:
            raise ValidationError("Informe o nome completo do cliente.")
        if len(name) > 64:
            raise ValidationError("O nome deve ter no máximo 64 caracteres para sincronizar com a Stone.")
        return name

    def clean_cpf_cnpj(self) -> str:
        document = validate_document(self.cleaned_data["cpf_cnpj"])
        existing = Cliente.objects.filter(cpf_cnpj=document).exclude(pk=self.instance.pk).first()
        if existing:
            raise ValidationError("Já existe um cliente cadastrado com este CPF/CNPJ.")
        return document

    def clean_telefone(self) -> str:
        return normalize_phone(self.cleaned_data["telefone"])

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if len(email) > 64:
            raise ValidationError("O e-mail deve ter no máximo 64 caracteres para sincronizar com a Stone.")
        existing = Cliente.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).first()
        if existing:
            raise ValidationError("Já existe um cliente cadastrado com este e-mail.")
        return email


class StoneCobrancaForm(forms.Form):
    cliente_id = forms.IntegerField(widget=forms.HiddenInput)
    valor = forms.CharField(max_length=32, label="Valor")
    referencia = forms.CharField(max_length=160, label="Referência")
    metodo = forms.ChoiceField(choices=Pagamento.Metodo.choices, widget=forms.RadioSelect, initial=Pagamento.Metodo.PIX)
    parcelas = forms.IntegerField(min_value=1, max_value=12, initial=1, required=False)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, required=False)
    card_token = forms.CharField(widget=forms.HiddenInput, required=False, max_length=255)
    saved_method_id = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, cliente: Cliente | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cliente = cliente

    def clean_cliente_id(self) -> int:
        client_id = self.cleaned_data["cliente_id"]
        try:
            self.cliente = Cliente.objects.get(pk=client_id)
        except Cliente.DoesNotExist as exc:
            raise ValidationError("Selecione um cliente válido antes de gerar a cobrança.") from exc
        return client_id

    def clean_valor(self):
        return parse_brl(self.cleaned_data["valor"])

    def clean_referencia(self) -> str:
        reference = " ".join(self.cleaned_data["referencia"].split())
        if len(reference) < 3:
            raise ValidationError("Informe uma referência com pelo menos 3 caracteres.")
        return reference

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("metodo")
        if not cleaned.get("idempotency_key"):
            cleaned["idempotency_key"] = uuid.uuid4()
        if method == Pagamento.Metodo.PIX:
            cleaned["parcelas"] = 1
        elif method == Pagamento.Metodo.CARTAO:
            token = (cleaned.get("card_token") or "").strip()
            saved_method_id = cleaned.get("saved_method_id")
            if bool(token) == bool(saved_method_id):
                raise ValidationError("Tokenize um cartão ou selecione um cartão salvo, mas não ambos.")
            if saved_method_id:
                if not self.cliente or not MetodoPagamento.objects.filter(
                    pk=saved_method_id, cliente=self.cliente, ativo=True
                ).exists():
                    raise ValidationError("O cartão salvo selecionado não está disponível para este cliente.")
        return cleaned
