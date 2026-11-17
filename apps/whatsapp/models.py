"""Chat de WhatsApp integrado (Evolution API).

Credenciais da Evolution ficam só nas variáveis de ambiente; aqui guardamos apenas o nome
da instância. Mídias ficam no armazenamento privado e só saem por view autenticada.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone


class ArmazenamentoPrivado(FileSystemStorage):
    """Pasta fora de MEDIA_ROOT (não servida em /media/); o caminho vem de WHATSAPP_MEDIA_ROOT a cada uso."""

    def __init__(self):
        super().__init__(base_url=None)

    @property
    def base_location(self):  # type: ignore[override]
        return str(settings.WHATSAPP_MEDIA_ROOT)

    @property
    def location(self):  # type: ignore[override]
        return os.path.abspath(self.base_location)


_armazenamento = ArmazenamentoPrivado()


def armazenamento_privado() -> ArmazenamentoPrivado:
    return _armazenamento


def caminho_midia(instance: "Mensagem", filename: str) -> str:
    agora = timezone.localtime()
    return f"whatsapp/{agora:%Y/%m}/{instance.conversa_id or 'novo'}_{filename}"


class Instancia(models.Model):
    """Número de WhatsApp (um por vendedora, e opcionalmente um da empresa).

    Na Umbler Talk (provedor padrão) corresponde a um *canal* da organização; na Evolution, a uma instância.
    """

    class Provedor(models.TextChoices):
        UMBLER = "umbler", "Umbler Talk"
        EVOLUTION = "evolution", "Evolution API"

    class Estado(models.TextChoices):
        CONECTADA = "open", "Conectada"
        CONECTANDO = "connecting", "Aguardando conexão"
        DESCONECTADA = "close", "Desconectada"
        DESCONHECIDO = "", "Não verificado"

    nome = models.CharField(
        "identificador interno", max_length=60, unique=True,
        help_text="Só letras minúsculas, números, hífen e sublinhado. Na Evolution, é o nome da instância. Ex.: pf_ana",
    )
    provedor = models.CharField("provedor", max_length=12, choices=Provedor.choices, default=Provedor.UMBLER)
    canal_id = models.CharField(
        "ID do canal na Umbler", max_length=40, blank=True, default="", db_index=True,
        help_text="Id do canal (GET /v1/channels/). Preenchido ao importar os canais da Umbler.",
    )
    telefone_canal = models.CharField(
        "telefone do canal (E.164)", max_length=20, blank=True, default="",
        help_text="Número que envia as mensagens, com DDI. Ex.: +5584999990000",
    )
    apelido = models.CharField("nome exibido", max_length=80)
    vendedora = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="instancias_whatsapp", verbose_name="vendedora dona do número",
    )
    compartilhada = models.BooleanField(
        "compartilhada com o atendimento", default=False,
        help_text="Número da empresa: todo o setor de atendimento vê as conversas.",
    )
    padrao_automaticas = models.BooleanField(
        "usar para mensagens automáticas", default=False,
        help_text="Usada quando o responsável do pedido não tem número próprio conectado.",
    )
    cor = models.CharField("cor da etiqueta", max_length=7, default="#3BA776")
    ativa = models.BooleanField("ativa", default=True)
    estado = models.CharField("estado da conexão", max_length=12, choices=Estado.choices, blank=True, default="")
    numero_conectado = models.CharField("número conectado", max_length=20, blank=True, default="")
    estado_verificado_em = models.DateTimeField("estado verificado em", null=True, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_whatsapp_instancias"
        ordering = ["apelido"]
        verbose_name = "Instância de WhatsApp"
        verbose_name_plural = "Instâncias de WhatsApp"

    def __str__(self) -> str:
        return self.apelido or self.nome


class Etiqueta(models.Model):
    nome = models.CharField("nome", max_length=40)
    cor = models.CharField("cor", max_length=7, default="#3BA776")
    vendedora = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name="etiquetas_whatsapp", verbose_name="vendedora (vazio = de todos)",
    )

    class Meta:
        db_table = "pf_whatsapp_etiquetas"
        ordering = ["nome"]
        verbose_name = "Etiqueta do chat"
        verbose_name_plural = "Etiquetas do chat"

    def __str__(self) -> str:
        return self.nome


class Conversa(models.Model):
    instancia = models.ForeignKey(Instancia, on_delete=models.PROTECT, related_name="conversas")
    # NULL (e não "") quando desconhecido: o MariaDB não aceita unicidade condicional, mas ignora NULLs.
    telefone = models.CharField("telefone (DDI+DDD+número)", max_length=20, null=True, blank=True)
    lid = models.CharField("LID do WhatsApp", max_length=40, null=True, blank=True)
    nome = models.CharField("nome do contato", max_length=150, blank=True, default="")
    cliente = models.ForeignKey(
        "payments.Cliente", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="conversas_whatsapp", verbose_name="cliente cadastrado",
    )
    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name="conversas")
    nao_lidas = models.PositiveIntegerField("não lidas", default=0)
    ultima_mensagem_em = models.DateTimeField("última mensagem em", default=timezone.now, db_index=True)
    ultima_previa = models.CharField("prévia", max_length=160, blank=True, default="")
    ultima_direcao = models.CharField(max_length=10, blank=True, default="")
    arquivada_em = models.DateTimeField("arquivada em", null=True, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pf_whatsapp_conversas"
        ordering = ["-ultima_mensagem_em", "-pk"]
        verbose_name = "Conversa de WhatsApp"
        verbose_name_plural = "Conversas de WhatsApp"
        constraints = [
            models.UniqueConstraint(fields=["instancia", "telefone"], name="pf_wa_conversa_telefone_unico"),
            models.UniqueConstraint(fields=["instancia", "lid"], name="pf_wa_conversa_lid_unico"),
        ]

    def __str__(self) -> str:
        return self.nome_exibicao

    @property
    def nome_exibicao(self) -> str:
        if self.cliente_id and self.cliente.nome:
            return self.cliente.nome
        from .telefone import formatar_telefone

        return self.nome or formatar_telefone(self.telefone) or "Contato do WhatsApp"

    @property
    def destino(self) -> str:
        """Para onde enviar: o número, ou o JID @lid enquanto o número não é conhecido."""
        return self.telefone or (f"{self.lid}@lid" if self.lid else "")


class Mensagem(models.Model):
    class Direcao(models.TextChoices):
        RECEBIDA = "in", "Recebida"
        ENVIADA = "out", "Enviada"

    class Tipo(models.TextChoices):
        TEXTO = "texto", "Texto"
        IMAGEM = "imagem", "Imagem"
        AUDIO = "audio", "Áudio"
        VIDEO = "video", "Vídeo"
        DOCUMENTO = "documento", "Documento"
        FIGURINHA = "figurinha", "Figurinha"
        LOCALIZACAO = "localizacao", "Localização"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Enviando"
        ENVIADA = "enviada", "Enviada"
        ENTREGUE = "entregue", "Entregue"
        LIDA = "lida", "Lida"
        FALHOU = "falhou", "Falhou"

    class Origem(models.TextChoices):
        CHAT = "chat", "Chat do sistema"
        CELULAR = "celular", "Fora do sistema (celular ou Umbler)"
        AUTOMATICA = "automatica", "Mensagem automática"
        CLIENTE = "cliente", "Cliente"

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name="mensagens")
    direcao = models.CharField(max_length=3, choices=Direcao.choices)
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.TEXTO)
    texto = models.TextField(blank=True, default="")
    arquivo = models.FileField(storage=armazenamento_privado, upload_to=caminho_midia, max_length=255, blank=True)
    arquivo_nome = models.CharField("nome do arquivo", max_length=160, blank=True, default="")
    mimetype = models.CharField(max_length=100, blank=True, default="")
    tamanho = models.PositiveIntegerField(default=0)
    midia_pendente = models.JSONField(
        "dados para baixar a mídia", null=True, blank=True,
        help_text="Chave da mensagem na Evolution; a mídia é baixada na primeira vez que alguém abre.",
    )
    id_externo = models.CharField("ID no WhatsApp", max_length=100, null=True, blank=True)
    remote_jid = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ENVIADA)
    erro = models.CharField("motivo da falha", max_length=255, blank=True, default="")
    origem = models.CharField(max_length=12, choices=Origem.choices, default=Origem.CHAT)
    remetente = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mensagens_whatsapp", verbose_name="enviada por",
    )
    pedido = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mensagens_whatsapp", verbose_name="pedido relacionado",
    )
    ocultada_em = models.DateTimeField("apagada para mim em", null=True, blank=True)
    ocultada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    revogada_em = models.DateTimeField("apagada para todos em", null=True, blank=True)
    revogada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Vazio quando foi o contato que apagou.",
    )
    criada_em = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "pf_whatsapp_mensagens"
        ordering = ["criada_em", "pk"]
        verbose_name = "Mensagem de WhatsApp"
        verbose_name_plural = "Mensagens de WhatsApp"
        constraints = [
            # Idempotência do webhook: a mesma mensagem do WhatsApp nunca é gravada duas vezes.
            models.UniqueConstraint(fields=["conversa", "id_externo"], name="pf_wa_msg_externa_unica"),
        ]
        indexes = [models.Index(fields=["conversa", "criada_em"], name="pf_wa_msg_conversa_idx")]

    def __str__(self) -> str:
        return f"{self.get_direcao_display()} {self.criada_em:%d/%m %H:%M}: {self.texto[:40]}"

    @property
    def revogada(self) -> bool:
        return self.revogada_em is not None

    @property
    def tem_midia(self) -> bool:
        return bool(self.arquivo) or bool(self.midia_pendente)


class EventoWebhook(models.Model):
    """Registro mínimo de cada evento recebido (sem o conteúdo da mensagem) para auditoria e reprocesso."""

    instancia = models.CharField(max_length=60)
    tipo = models.CharField(max_length=40)
    chave = models.CharField("identificador do evento", max_length=140)
    recebido_em = models.DateTimeField(auto_now_add=True, db_index=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pf_whatsapp_eventos"
        ordering = ["-recebido_em"]
        verbose_name = "Evento do webhook do WhatsApp"
        verbose_name_plural = "Eventos do webhook do WhatsApp"
        constraints = [models.UniqueConstraint(fields=["instancia", "tipo", "chave"], name="pf_wa_evento_unico")]
