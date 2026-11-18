"""Cofre das chaves de integração (Stone/Pagar.me e Umbler Talk).

`valor(nome)` devolve a chave salva pela página de desenvolvedor (criptografada no banco) ou, se não houver,
o valor do .env (settings). Nada aqui loga ou devolve a chave inteira para exibição: só os 4 últimos caracteres.

Chaves da Stone são guardadas por ambiente (`STONE_SECRET_KEY:sandbox`, `STONE_SECRET_KEY:production`), assim
trocar `STONE_ENVIRONMENT` no .env nunca faz o sistema usar uma chave do outro ambiente.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import DatabaseError

logger = logging.getLogger("integracoes")


@dataclass(frozen=True)
class Campo:
    nome: str
    grupo: str
    rotulo: str
    ajuda: str = ""
    gerar: bool = False  # segredo que o próprio sistema pode gerar (webhooks)


CAMPOS: tuple[Campo, ...] = (
    Campo("STONE_SECRET_KEY", "stone", "Chave secreta (sk_…)",
          "Usada pelo servidor para PIX, cartão e links de pagamento."),
    Campo("STONE_PUBLIC_KEY", "stone", "Chave pública (pk_…)", "Usada no navegador para tokenizar o cartão."),
    Campo("STONE_ACCOUNT_ID", "stone", "ID da conta (acc_…)", "Opcional."),
    Campo("STONE_WEBHOOK_SECRET", "stone", "Segredo do webhook",
          "Opcional. Usado para conferir a assinatura dos avisos da Stone."),
    Campo("UMBLER_API_TOKEN", "umbler", "Token da API",
          "Gerado em account.umbler.com/profile (plano Enterprise)."),
    Campo("UMBLER_ORGANIZATION_ID", "umbler", "ID da organização", "Retornado por GET /v1/members/me/."),
    Campo("UMBLER_WEBHOOK_SECRET", "umbler", "Segredo do webhook",
          "Vai no final da URL do webhook cadastrada no painel da Umbler.", gerar=True),
)
POR_NOME = {c.nome: c for c in CAMPOS}

SEGREDO_URL = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


class ChaveInvalida(ValueError):
    pass


def ambiente_stone() -> str:
    return (getattr(settings, "STONE_ENVIRONMENT", "sandbox") or "sandbox").strip().lower()


def stone_em_producao() -> bool:
    return ambiente_stone() == "production"


def nome_armazenado(nome: str) -> str:
    if nome.startswith("STONE_"):
        return f"{nome}:{ambiente_stone()}"
    return nome


def final(valor: str) -> str:
    return (valor or "")[-4:]


def mascarar(valor: str) -> str:
    return f"…{final(valor)}" if valor else ""


# --- criptografia ------------------------------------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet

    mestra = (getattr(settings, "INTEGRACOES_CHAVE_MESTRA", "") or "").strip()
    if mestra:
        return Fernet(mestra.encode())
    # Sem chave mestra própria, deriva uma da SECRET_KEY (trocar a SECRET_KEY invalida as chaves salvas).
    material = hashlib.sha256(b"print-fornece:integracoes:" + settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def cifrar(valor: str) -> str:
    return _fernet().encrypt(valor.encode()).decode()


def decifrar(texto: str) -> str | None:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(texto.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# --- leitura -----------------------------------------------------------------------------------------------

def _registro(nome: str):
    from .models import ChaveIntegracao

    try:
        return ChaveIntegracao.objects.filter(nome=nome_armazenado(nome)).first()
    except DatabaseError:
        # Banco indisponível ou migração ainda não aplicada: segue com o .env.
        return None


def valor(nome: str) -> str:
    """Chave em uso: a salva pela página de desenvolvedor ou, se não houver, a do .env."""
    registro = _registro(nome)
    if registro is not None:
        texto = decifrar(registro.valor_cifrado)
        if texto is not None:
            return texto
        logger.warning("Chave %s salva no painel não pôde ser lida (chave mestra mudou?); usando o .env.", nome)
    return (getattr(settings, nome, "") or "").strip()


def situacao(nome: str) -> dict:
    """Resumo para a página: origem e 4 últimos caracteres. Nunca devolve a chave."""
    registro = _registro(nome)
    if registro is not None:
        legivel = decifrar(registro.valor_cifrado) is not None
        return {
            "origem": "painel" if legivel else "ilegivel",
            "final": registro.final,
            "atualizado_em": registro.atualizado_em,
            "atualizado_por": registro.atualizado_por,
            "tem_registro": True,
        }
    do_env = (getattr(settings, nome, "") or "").strip()
    return {
        "origem": "env" if do_env else "vazia",
        "final": final(do_env),
        "atualizado_em": None,
        "atualizado_por": None,
        "tem_registro": False,
    }


# --- validação e gravação ----------------------------------------------------------------------------------

def validar(nome: str, texto: str) -> str:
    """Normaliza e valida no servidor. Mantém a trava de ambiente da Stone pelo prefixo da chave."""
    texto = (texto or "").strip()
    if not texto:
        raise ChaveInvalida("Informe um valor.")
    if len(texto) > 500 or any(c.isspace() for c in texto):
        raise ChaveInvalida("O valor não pode ter espaços nem passar de 500 caracteres.")
    producao = stone_em_producao()
    if nome == "STONE_SECRET_KEY":
        if not texto.startswith("sk_"):
            raise ChaveInvalida("A chave secreta da Stone começa com 'sk_'.")
        if producao and texto.startswith("sk_test_"):
            raise ChaveInvalida("O ambiente é produção: chave 'sk_test_' não é aceita.")
        if not producao and not texto.startswith("sk_test_"):
            raise ChaveInvalida(f"O ambiente é {ambiente_stone()}: use uma chave de teste 'sk_test_'.")
    elif nome == "STONE_PUBLIC_KEY":
        if not texto.startswith("pk_"):
            raise ChaveInvalida("A chave pública da Stone começa com 'pk_'.")
        if producao and texto.startswith("pk_test_"):
            raise ChaveInvalida("O ambiente é produção: chave 'pk_test_' não é aceita.")
        if not producao and not texto.startswith("pk_test_"):
            raise ChaveInvalida(f"O ambiente é {ambiente_stone()}: use uma chave de teste 'pk_test_'.")
    elif nome == "UMBLER_WEBHOOK_SECRET":
        if not SEGREDO_URL.match(texto):
            raise ChaveInvalida("Use de 24 a 128 caracteres entre letras, números, '-' e '_' (vai na URL).")
    elif nome == "STONE_WEBHOOK_SECRET" and len(texto) < 8:
        raise ChaveInvalida("O segredo precisa ter pelo menos 8 caracteres.")
    return texto


def gerar_segredo() -> str:
    return secrets.token_urlsafe(32)


def salvar(nome: str, texto: str, usuario) -> None:
    from .models import ChaveIntegracao

    if nome not in POR_NOME:
        raise ChaveInvalida("Chave desconhecida.")
    texto = validar(nome, texto)
    ChaveIntegracao.objects.update_or_create(
        nome=nome_armazenado(nome),
        defaults={"valor_cifrado": cifrar(texto), "final": final(texto), "atualizado_por": usuario},
    )


def remover(nome: str) -> bool:
    from .models import ChaveIntegracao

    apagados, _ = ChaveIntegracao.objects.filter(nome=nome_armazenado(nome)).delete()
    return bool(apagados)
