from __future__ import annotations

from django.conf import settings
from django.db import models


class ChaveIntegracao(models.Model):
    """Chave de API salva pela página de desenvolvedor. O valor fica sempre criptografado (Fernet).

    Quando existe registro aqui ele tem prioridade sobre o .env; apagar o registro volta a usar o .env.
    Guarda só os 4 últimos caracteres em claro, para exibição.
    """

    nome = models.CharField("nome", max_length=80, unique=True)
    valor_cifrado = models.TextField("valor criptografado")
    final = models.CharField("4 últimos caracteres", max_length=4, blank=True, default="")
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="atualizado por", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        db_table = "pf_chaves_integracao"
        verbose_name = "chave de integração"
        verbose_name_plural = "chaves de integração"

    def __str__(self) -> str:
        return f"{self.nome} (…{self.final})"
