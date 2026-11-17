"""Cliente da API da Umbler Talk (uTalk) — https://app-utalk.umbler.com/api/docs/index.html

Conferido no OpenAPI oficial (v1) em 17/11/2026:
- Autenticação: ``Authorization: Bearer <token>`` (token gerado em https://account.umbler.com/profile).
- Quase toda rota exige ``organizationId`` (descoberto em GET /v1/members/me/).
- Telefones sempre em E.164: ``+5584999991234``.
- Envio: POST /v1/messages/simplified/ (JSON para texto, multipart/form-data para arquivo).
  Um 200 só quer dizer "entrou na fila": o estado real vem em ``messageState`` (GET /v1/messages/{id}/).
- Apagar: DELETE /v1/messages/{id}/?organizationId=…&deleteForEveryone=true|false
- Canais (números): GET /v1/channels/?organizationId=… → id, name, phoneNumber, state ("Live" = conectado).
- Limites: 250 envios / 5 s; 100 consultas / 5 s.

O token nunca vai para log nem para o navegador.
"""
from __future__ import annotations

import json
import logging
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from .telefone import telefone_canonico

logger = logging.getLogger("whatsapp")

BASE_PADRAO = "https://app-utalk.umbler.com/api"

# messageState da Umbler -> status do Print
ESTADOS_MENSAGEM = {
    "processing": "pendente",
    "submitted": "pendente",
    "retrying": "pendente",
    "sent": "enviada",
    "received": "entregue",
    "read": "lida",
    "played": "lida",
    "failed": "falhou",
    "error": "falhou",
}
# state do canal -> estado da instância
ESTADOS_CANAL = {
    "live": "open",
    "probation": "open",
    "waitingfirstsync": "connecting",
    "waitingtogolive": "connecting",
    "waitingappcreation": "connecting",
    "offline": "close",
    "disabled": "close",
    "deleted": "close",
}


class UmblerErro(RuntimeError):
    """Falha de comunicação ou recusa da Umbler; a mensagem já é amigável para a equipe."""


class UmblerNaoConfigurada(UmblerErro):
    pass


@dataclass
class Resposta:
    ok: bool
    status_http: int = 0
    dados: Any = field(default_factory=dict)
    erro: str = ""


def e164(telefone: str) -> str:
    """'84 99999-1234' -> '+5584999991234' (o formato que a Umbler exige)."""
    canonico = telefone_canonico(telefone)
    return f"+{canonico}" if canonico else ""


def campo(obj: Any, nome: str, padrao: Any = None) -> Any:
    """Lê uma chave sem depender de maiúsculas: a API responde em camelCase e o webhook em PascalCase."""
    if not isinstance(obj, dict):
        return padrao
    if nome in obj:
        return obj[nome]
    alvo = nome.lower()
    for chave, valor in obj.items():
        if isinstance(chave, str) and chave.lower() == alvo:
            return valor
    return padrao


def _multipart(campos: dict[str, str], arquivo: tuple[str, str, bytes] | None) -> tuple[bytes, str]:
    fronteira = f"----printfornece{uuid.uuid4().hex}"
    partes: list[bytes] = []
    for nome, valor in campos.items():
        partes.append(
            f'--{fronteira}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n{valor}\r\n'.encode("utf-8")
        )
    if arquivo:
        nome_arquivo, mimetype, conteudo = arquivo
        seguro = nome_arquivo.replace('"', "").replace("\r", "").replace("\n", "")
        partes.append(
            (
                f'--{fronteira}\r\nContent-Disposition: form-data; name="File"; filename="{seguro}"\r\n'
                f"Content-Type: {mimetype or 'application/octet-stream'}\r\n\r\n"
            ).encode("utf-8")
            + conteudo
            + b"\r\n"
        )
    partes.append(f"--{fronteira}--\r\n".encode("utf-8"))
    return b"".join(partes), f"multipart/form-data; boundary={fronteira}"


class UmblerClient:
    def __init__(self, *, base_url: str | None = None, token: str | None = None, organizacao: str | None = None, timeout: int | None = None):
        self.base_url = (base_url if base_url is not None else getattr(settings, "UMBLER_API_URL", "") or BASE_PADRAO).rstrip("/")
        self.token = token if token is not None else getattr(settings, "UMBLER_API_TOKEN", "")
        self.organizacao = organizacao if organizacao is not None else getattr(settings, "UMBLER_ORGANIZATION_ID", "")
        self.timeout = timeout or int(getattr(settings, "UMBLER_TIMEOUT_SECONDS", 20))

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.organizacao)

    def _requisicao(self, metodo: str, caminho: str, *, query: dict[str, Any] | None = None, corpo: Any = None,
                    multipart: tuple[dict[str, str], tuple[str, str, bytes] | None] | None = None, timeout: int | None = None) -> Resposta:
        if not self.configurado:
            raise UmblerNaoConfigurada("A API da Umbler ainda não foi configurada (UMBLER_API_TOKEN / UMBLER_ORGANIZATION_ID).")
        url = f"{self.base_url}/{caminho.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        dados = None
        if multipart is not None:
            dados, headers["Content-Type"] = _multipart(*multipart)
        elif corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=dados, method=metodo, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:  # noqa: S310 - URL fixa do .env
                bruto = resp.read().decode("utf-8")
                return Resposta(True, resp.status, json.loads(bruto) if bruto else {})
        except urllib.error.HTTPError as exc:
            bruto = exc.read().decode("utf-8", errors="ignore")
            try:
                conteudo = json.loads(bruto) if bruto else {}
            except json.JSONDecodeError:
                conteudo = {}
            detalhe = str(campo(conteudo, "title") or campo(conteudo, "detail") or "")[:160] if isinstance(conteudo, dict) else ""
            # Só código, rota e título do erro vão para o log: o corpo pode ter telefone e texto do cliente.
            logger.warning("Umbler respondeu HTTP %s em %s %s: %s", exc.code, metodo, caminho.split("?")[0], detalhe)
            return Resposta(False, exc.code, conteudo, f"HTTP {exc.code}" + (f": {detalhe}" if detalhe else ""))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Umbler inacessível (%s)", type(exc).__name__)
            return Resposta(False, 0, {}, "Servidor da Umbler inacessível")
        except json.JSONDecodeError:
            return Resposta(False, 0, {}, "Resposta inválida da Umbler")

    # ------------------------------------------------------------------ envio
    def enviar_texto(self, *, de: str, para: str, texto: str, nome_contato: str = "") -> Resposta:
        corpo = {
            "toPhone": e164(para),
            "fromPhone": e164(de),
            "organizationId": self.organizacao,
            "message": texto,
            "skipReassign": True,
        }
        if nome_contato:
            corpo["contactName"] = nome_contato[:100]
        return self._requisicao("POST", "/v1/messages/simplified/", corpo=corpo)

    def enviar_arquivo(self, *, de: str, para: str, conteudo: bytes, nome_arquivo: str, mimetype: str, legenda: str = "") -> Resposta:
        campos = {"ToPhone": e164(para), "FromPhone": e164(de), "OrganizationId": self.organizacao, "SkipReassign": "true"}
        if legenda:
            campos["Message"] = legenda
        return self._requisicao("POST", "/v1/messages/simplified/", multipart=(campos, (nome_arquivo, mimetype, conteudo)), timeout=60)

    def apagar(self, id_mensagem: str, *, para_todos: bool) -> Resposta:
        return self._requisicao(
            "DELETE", f"/v1/messages/{urllib.parse.quote(id_mensagem, safe='')}/",
            query={"organizationId": self.organizacao, "deleteForEveryone": "true" if para_todos else "false"},
        )

    def mensagem(self, id_mensagem: str) -> Resposta:
        return self._requisicao("GET", f"/v1/messages/{urllib.parse.quote(id_mensagem, safe='')}/", query={"organizationId": self.organizacao})

    def baixar_arquivo_da_mensagem(self, id_mensagem: str, limite_bytes: int) -> tuple[bytes, str, str]:
        """Pega a URL do arquivo pela própria API (nunca a URL que veio no webhook) e baixa o conteúdo."""
        res = self.mensagem(id_mensagem)
        if not res.ok:
            raise UmblerErro("Não foi possível consultar a mensagem na Umbler.")
        arquivo = campo(res.dados, "file") or {}
        url = str(campo(arquivo, "url") or "")
        if not url.startswith("https://"):
            raise UmblerErro("A Umbler não devolveu o arquivo desta mensagem.")
        req = urllib.request.Request(url, headers={"Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - URL https vinda da API autenticada
                conteudo = resp.read(limite_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UmblerErro("Falha ao baixar o arquivo da Umbler.") from exc
        if len(conteudo) > limite_bytes:
            raise UmblerErro("Arquivo grande demais para guardar no sistema.")
        return conteudo, str(campo(arquivo, "contentType") or ""), str(campo(arquivo, "originalName") or "")

    # ----------------------------------------------------------------- canais
    def canais(self) -> list[dict[str, Any]]:
        res = self._requisicao("GET", "/v1/channels/", query={"organizationId": self.organizacao})
        if not res.ok:
            raise UmblerErro(res.erro or "Falha ao listar os canais da Umbler.")
        return [c for c in (res.dados if isinstance(res.dados, list) else []) if isinstance(c, dict)]

    def canal(self, canal_id: str) -> dict[str, Any]:
        res = self._requisicao("GET", f"/v1/channels/{urllib.parse.quote(canal_id, safe='')}/", query={"organizationId": self.organizacao})
        if not res.ok:
            raise UmblerErro(res.erro or "Falha ao consultar o canal na Umbler.")
        return res.dados if isinstance(res.dados, dict) else {}
