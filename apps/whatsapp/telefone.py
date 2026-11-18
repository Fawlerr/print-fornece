"""Normalização de telefones brasileiros e identificadores do WhatsApp.

Regras trazidas do chat da Casa das Óticas, onde já resolveram duplicidade de contatos:
- a chave de comparação é sempre DDI 55 + DDD + número, com o 9º dígito nos celulares;
- o número inteiro é comparado, para não juntar clientes de DDDs diferentes com o mesmo final;
- o WhatsApp pode identificar o contato por LID (``123@lid``), que não é telefone.
"""
from __future__ import annotations

import re

_NAO_DIGITO = re.compile(r"\D")


def so_digitos(valor: str | None) -> str:
    return _NAO_DIGITO.sub("", valor or "")


def com_ddi(telefone: str | None) -> str:
    """Só dígitos, com DDI 55 quando o número veio apenas com DDD + número."""
    digitos = so_digitos(telefone)
    if len(digitos) in (10, 11) and not digitos.startswith("55"):
        digitos = f"55{digitos}"
    return digitos


def telefone_canonico(telefone: str | None) -> str:
    """Chave de comparação: "84 9999-1234", "558499991234" e "+55 (84) 99999-1234" viram a mesma."""
    digitos = com_ddi(telefone)
    if digitos.startswith("55") and len(digitos) == 12 and digitos[4] in "6789":
        digitos = f"{digitos[:4]}9{digitos[4:]}"
    return digitos


def variantes_envio(telefone: str) -> list[str]:
    """Destinos a tentar no envio: o canônico e, para celular BR, a versão sem o 9º dígito."""
    if "@lid" in (telefone or ""):
        return [telefone]
    canonico = telefone_canonico(telefone)
    if canonico.startswith("55") and len(canonico) == 13 and canonico[4] == "9":
        return [canonico, canonico[:4] + canonico[5:]]
    return [canonico] if canonico else []


def digitos_do_jid(jid: str | None) -> str:
    """'5584999991234:12@s.whatsapp.net' -> '5584999991234'."""
    return so_digitos(str(jid or "").split("@")[0].split(":")[0])


def telefone_valido(telefone: str | None) -> bool:
    canonico = telefone_canonico(telefone)
    return canonico.startswith("55") and len(canonico) in (12, 13)


def formatar_telefone(telefone: str | None) -> str:
    """'5584999991234' -> '(84) 99999-1234' (outros formatos voltam como vieram)."""
    canonico = telefone_canonico(telefone)
    if canonico.startswith("55") and len(canonico) == 13:
        return f"({canonico[2:4]}) {canonico[4:9]}-{canonico[9:]}"
    if canonico.startswith("55") and len(canonico) == 12:
        return f"({canonico[2:4]}) {canonico[4:8]}-{canonico[8:]}"
    return telefone or ""
