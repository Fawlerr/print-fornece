import uuid
from django.db import models
from django.utils import timezone

from apps.orders.models import Order


def cliente_upload_path(instance: "ClienteArquivo", filename: str) -> str:
    from pathlib import Path
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

    @property
    def cpf_cnpj_mascarado(self) -> str:
        from apps.payments.stone.services.normalizers import mask_document
        return mask_document(self.cpf_cnpj or "")

    @property
    def telefone_formatado(self) -> str:
        from apps.payments.stone.services.normalizers import format_phone
        return format_phone(self.telefone or "")



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


# ==============================================================================
# Modelos Stone / Pagar.me V5 (Ambiente de Homologação / Testes)
# ==============================================================================


class StoneLogIntegracao(models.Model):
    class Nivel(models.TextChoices):
        INFO = "INFO", "Info"
        SUCCESS = "SUCCESS", "Success"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        REQUEST = "REQUEST", "Request"
        RESPONSE = "RESPONSE", "Response"
        DEBUG = "DEBUG", "Debug"

    trace_id = models.CharField(max_length=64, db_index=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    nivel = models.CharField(max_length=15, choices=Nivel.choices, default=Nivel.INFO, db_index=True)
    tipo_evento = models.CharField(max_length=64, db_index=True)
    mensagem = models.TextField()

    # Detalhes HTTP e Telemetria
    endpoint = models.CharField(max_length=255, blank=True)
    metodo_http = models.CharField(max_length=10, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    duracao_ms = models.PositiveIntegerField(null=True, blank=True)

    # Identificadores da Integração
    order_id = models.CharField(max_length=100, blank=True, db_index=True)
    charge_id = models.CharField(max_length=100, blank=True, db_index=True)
    transaction_id = models.CharField(max_length=100, blank=True, db_index=True)

    # Detalhes de Erro da API
    error_code = models.CharField(max_length=80, blank=True)
    error_type = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    error_parameter = models.CharField(max_length=120, blank=True)

    # Payloads completos e sanitizados para inspeção técnica
    request_headers = models.JSONField(default=dict, blank=True)
    request_body = models.JSONField(default=dict, blank=True)
    response_headers = models.JSONField(default=dict, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    detalhes_extras = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "pf_stone_logs"
        ordering = ["-timestamp", "-pk"]
        indexes = [
            models.Index(fields=["trace_id", "timestamp"], name="pf_stone_log_tr_ts_idx"),
            models.Index(fields=["nivel", "timestamp"], name="pf_stone_log_nv_ts_idx"),
            models.Index(fields=["order_id", "timestamp"], name="pf_stone_log_ord_ts_idx"),
        ]
        verbose_name = "Log de Integração Stone"
        verbose_name_plural = "Logs de Integração Stone"

    def __str__(self) -> str:
        return f"[{self.nivel}] {self.tipo_evento} - {self.mensagem[:50]}"


class StonePagamento(models.Model):
    class Metodo(models.TextChoices):
        PIX = "pix", "PIX"
        CARTAO = "cartao", "Cartão"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PAID = "paid", "Pago"
        FAILED = "failed", "Falhou"
        CANCELED = "canceled", "Cancelado"
        REFUNDED = "refunded", "Estornado"

    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name="stone_pagamentos")
    cliente_nome = models.CharField("Nome do Cliente", max_length=120, blank=True)
    cliente_documento = models.CharField("CPF/CNPJ", max_length=20, blank=True)
    cliente_email = models.CharField("E-mail", max_length=120, blank=True)
    cliente_telefone = models.CharField("Telefone", max_length=30, blank=True)

    stone_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    stone_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    stone_transaction_id = models.CharField(max_length=100, blank=True, db_index=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    metodo = models.CharField(max_length=10, choices=Metodo.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    parcelas = models.PositiveSmallIntegerField(default=1)
    referencia = models.CharField(max_length=160)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    response_data = models.JSONField(default=dict, blank=True)
    pix_qr_code = models.TextField(blank=True)
    pix_qr_code_url = models.URLField(blank=True)
    last_error_message = models.CharField(max_length=255, blank=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    submission_started_at = models.DateTimeField(null=True, blank=True)
    idempotency_expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pf_stone_pagamentos"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="pf_stone_pag_status_idx"),
            models.Index(fields=["metodo", "status"], name="pf_stone_pag_met_st_idx"),
        ]
        verbose_name = "Pagamento Stone (Teste)"
        verbose_name_plural = "Pagamentos Stone (Teste)"

    def __str__(self) -> str:
        client_name = self.cliente.nome if self.cliente else (self.cliente_nome or "Avulso")
        return f"Stone #{self.pk} — {client_name} — R$ {self.valor}"

    @property
    def is_pix(self) -> bool:
        return self.metodo == self.Metodo.PIX

    @property
    def is_card(self) -> bool:
        return self.metodo == self.Metodo.CARTAO


class StoneMetodoPagamento(models.Model):
    class Tipo(models.TextChoices):
        CARTAO = "cartao", "Cartão"

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="stone_metodos_pagamento")
    stone_payment_method_id = models.CharField(max_length=100, unique=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.CARTAO)
    bandeira = models.CharField(max_length=30, blank=True)
    ultimos_4 = models.CharField(max_length=4, blank=True)
    validade_mes = models.PositiveSmallIntegerField(null=True, blank=True)
    validade_ano = models.PositiveSmallIntegerField(null=True, blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pf_stone_metodos_pagamento"
        ordering = ["-ativo", "-updated_at", "-pk"]
        verbose_name = "Método de Pagamento Stone (Teste)"
        verbose_name_plural = "Métodos de Pagamento Stone (Teste)"

    def __str__(self) -> str:
        client_name = self.cliente.nome if self.cliente else "Cliente"
        suffix = f" •••• {self.ultimos_4}" if self.ultimos_4 else ""
        return f"{client_name} — {self.bandeira or 'Cartão'}{suffix}"


class StoneEventoPagamento(models.Model):
    pagamento = models.ForeignKey(StonePagamento, null=True, blank=True, on_delete=models.SET_NULL, related_name="eventos")
    cliente = models.ForeignKey(Cliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="stone_eventos_pagamento")
    tipo = models.CharField(max_length=60, db_index=True)
    descricao = models.TextField()
    dados = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_stone_eventos"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["pagamento", "created_at"], name="pf_stone_ev_pag_idx")]
        verbose_name = "Evento Stone (Teste)"
        verbose_name_plural = "Eventos Stone (Teste)"

    def __str__(self) -> str:
        return f"{self.tipo} em {timezone.localtime(self.created_at):%d/%m/%Y %H:%M}" if self.created_at else self.tipo



