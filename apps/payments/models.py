from django.db import models

from apps.orders.models import Order


def cliente_upload_path(instance: "ClienteArquivo", filename: str) -> str:
    from pathlib import Path
    import uuid
    extension = Path(filename).suffix.lower()
    token = uuid.uuid4().hex
    return f"cliente_arquivos/{instance.cliente_id or 'geral'}/{token}{extension}"


class Cliente(models.Model):
    nome = models.CharField("nome", max_length=200)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=20, null=True, blank=True, db_index=True)
    email = models.EmailField("e-mail", null=True, blank=True)
    telefone = models.CharField("telefone / WhatsApp", max_length=25, null=True, blank=True)
    preco_especial_metro = models.DecimalField("preço especial DTF/metro", max_digits=10, decimal_places=2, null=True, blank=True, help_text="Preço diferenciado do metro de DTF (ex: R$ 35,00)")
    saldo_credito = models.DecimalField("saldo em créditos (R$)", max_digits=12, decimal_places=2, default=0, help_text="Saldo financeiro para abatimento em pedidos")
    metros_saldo = models.DecimalField("saldo em metros do pacote", max_digits=10, decimal_places=2, default=0, help_text="Metros contratados no Plano de Volume")
    observacoes = models.TextField("observações do cliente", blank=True, default="")
    stone_customer_id = models.CharField("ID do Cliente Stone", max_length=100, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        db_table = "pf_clientes"
        ordering = ["nome"]
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self) -> str:
        return self.nome


class ClienteArquivo(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="arquivos_registrados", verbose_name="cliente")
    nome = models.CharField("nome do arquivo / descrição", max_length=255)
    arquivo = models.FileField("arquivo", upload_to=cliente_upload_path)
    content_type = models.CharField(max_length=100, blank=True, default="")
    tamanho = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        db_table = "pf_cliente_arquivos"
        ordering = ["-created_at", "-pk"]
        verbose_name = "Arquivo Registrado do Cliente"
        verbose_name_plural = "Arquivos Registrados dos Clientes"

    def __str__(self) -> str:
        return f"{self.cliente.nome} - {self.nome}"


class Pagamento(models.Model):
    class Metodo(models.TextChoices):
        PIX = "pix", "PIX"
        CARD = "cartao", "Cartão"

    class Status(models.TextChoices):
        PENDING = "pendente", "Pendente"
        PAID = "pago", "Pago"
        FAILED = "falhado", "Falhado"
        CANCELLED = "cancelado", "Cancelado"

    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name="pagamentos", verbose_name="cliente")
    stone_payment_id = models.CharField("ID do Pagamento Stone", max_length=100, null=True, blank=True, db_index=True)
    valor = models.DecimalField("valor", max_digits=12, decimal_places=2)
    metodo = models.CharField("método", max_length=20, choices=Metodo.choices, default=Metodo.PIX)
    status = models.CharField("situação", max_length=50, choices=Status.choices, default=Status.PENDING)
    parcelas = models.IntegerField("parcelas", default=1)
    pedido_referencia = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="pagamentos_stone", verbose_name="pedido de referência")
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        db_table = "pf_pagamentos"
        ordering = ["-created_at"]
        verbose_name = "Pagamento"
        verbose_name_plural = "Pagamentos"
        indexes = [
            models.Index(fields=["cliente"], name="pf_pag_cliente"),
            models.Index(fields=["stone_payment_id"], name="pf_pag_stone_id"),
            models.Index(fields=["status"], name="pf_pag_status"),
        ]

    def __str__(self) -> str:
        return f"Pagamento #{self.pk} - R$ {self.valor} ({self.get_status_display()})"


class MetodoPagamento(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="metodos_pagamento", verbose_name="cliente")
    stone_token_id = models.CharField("Token Stone", max_length=100)
    bandeira = models.CharField("bandeira", max_length=50, blank=True)
    ultimos_4 = models.CharField("últimos 4 dígitos", max_length=4)
    validade = models.CharField("validade", max_length=10, blank=True)
    ativo = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        db_table = "pf_metodos_pagamento"
        ordering = ["-created_at"]
        verbose_name = "Método de Pagamento"
        verbose_name_plural = "Métodos de Pagamento"

    def __str__(self) -> str:
        return f"{self.bandeira or 'Cartão'} **** {self.ultimos_4}"


class Charge(models.Model):
    class Type(models.TextChoices):
        PIX = "pix", "PIX"
        CARD = "cartao", "Cartão"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="charges")
    provider = models.CharField(max_length=50, default="stone")
    type = models.CharField(max_length=10, choices=Type.choices)
    external_identifier = models.CharField(max_length=190, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=50, default="pendente")
    pix_copy_paste = models.TextField(blank=True)
    checkout_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pf_charges"
        indexes = [models.Index(fields=["order"], name="pf_charge_order"), models.Index(fields=["external_identifier"], name="pf_charge_external")]


