"""Cliente único da Evolution API. Nenhum outro módulo faz HTTP para a Evolution.

URL e chave vêm das variáveis de ambiente (EVOLUTION_API_URL / EVOLUTION_API_KEY); a chave
nunca é registrada em log nem devolvida ao navegador.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from .telefone import variantes_envio

logger = logging.getLogger("whatsapp")

EVENTOS_WEBHOOK = (
    "QRCODE_UPDATED",
    "CONNECTION_UPDATE",
    "MESSAGES_UPSERT",
    "MESSAGES_UPDATE",
    "MESSAGES_DELETE",
    "CONTACTS_UPSERT",
    "CHATS_UPSERT",
)
_NOME_INSTANCIA = re.compile(r"^[a-z0-9_-]{2,60}$")


class EvolutionErro(RuntimeError):
    """Falha de comunicação ou recusa da Evolution; a mensagem já é amigável para a equipe."""


class EvolutionNaoConfigurada(EvolutionErro):
    pass


@dataclass
class Resultado:
    ok: bool
    status_http: int = 0
    dados: dict[str, Any] = field(default_factory=dict)
    erro: str = ""

    @property
    def id_mensagem(self) -> str:
        chave = self.dados.get("key") or (self.dados.get("message") or {}).get("key") or {}
        return str(chave.get("id") or "")

    @property
    def remote_jid(self) -> str:
        chave = self.dados.get("key") or (self.dados.get("message") or {}).get("key") or {}
        return str(chave.get("remoteJid") or "")


def nome_instancia_valido(nome: str) -> bool:
    return bool(_NOME_INSTANCIA.match(nome or ""))


def url_webhook() -> str:
    base = (getattr(settings, "EVOLUTION_WEBHOOK_BASE_URL", "") or "").rstrip("/")
    segredo = getattr(settings, "EVOLUTION_WEBHOOK_SECRET", "") or ""
    if not base or not segredo:
        raise EvolutionNaoConfigurada("Defina EVOLUTION_WEBHOOK_BASE_URL e EVOLUTION_WEBHOOK_SECRET.")
    return f"{base}/chat/webhook/evolution/{segredo}/"


class EvolutionClient:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, versao: str | None = None, timeout: int | None = None):
        self.base_url = (base_url if base_url is not None else getattr(settings, "EVOLUTION_API_URL", "")).rstrip("/")
        self.api_key = api_key if api_key is not None else getattr(settings, "EVOLUTION_API_KEY", "")
        self.versao = str(versao or getattr(settings, "EVOLUTION_API_VERSION", "2"))
        self.timeout = timeout or int(getattr(settings, "EVOLUTION_TIMEOUT_SECONDS", 15))

    @property
    def configurado(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _requisicao(self, metodo: str, caminho: str, corpo: dict[str, Any] | None = None, *, timeout: int | None = None) -> Resultado:
        if not self.configurado:
            raise EvolutionNaoConfigurada("A Evolution API ainda não foi configurada (EVOLUTION_API_URL / EVOLUTION_API_KEY).")
        url = f"{self.base_url}/{caminho.lstrip('/')}"
        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        req = urllib.request.Request(
            url, data=dados, method=metodo,
            headers={"apikey": self.api_key, "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:  # noqa: S310 - URL do .env
                bruto = resp.read().decode("utf-8")
                conteudo = json.loads(bruto) if bruto else {}
                return Resultado(True, resp.status, conteudo if isinstance(conteudo, dict) else {"lista": conteudo})
        except urllib.error.HTTPError as exc:
            bruto = exc.read().decode("utf-8", errors="ignore")
            try:
                conteudo = json.loads(bruto) if bruto else {}
            except json.JSONDecodeError:
                conteudo = {}
            # Só o código e o tipo vão para o log: o corpo pode ter telefone e texto do cliente.
            logger.warning("Evolution respondeu HTTP %s em %s %s", exc.code, metodo, caminho.split("/")[1] if "/" in caminho else caminho)
            return Resultado(False, exc.code, conteudo if isinstance(conteudo, dict) else {}, f"HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Evolution inacessível (%s)", type(exc).__name__)
            return Resultado(False, 0, {}, "Servidor do WhatsApp inacessível")

    # ------------------------------------------------------------------ envio
    def _tentar_destinos(self, destino: str, montar) -> Resultado:
        ultimo = Resultado(False, erro="Número inválido")
        for numero in variantes_envio(destino):
            caminho, corpo, timeout = montar(numero)
            ultimo = self._requisicao("POST", caminho, corpo, timeout=timeout)
            if ultimo.ok:
                return ultimo
            if ultimo.status_http == 0:
                break
        return ultimo

    def enviar_texto(self, instancia: str, destino: str, texto: str) -> Resultado:
        def montar(numero: str):
            corpo: dict[str, Any] = {"number": numero, "text": texto, "linkPreview": True}
            if self.versao.startswith("1"):
                corpo = {"number": numero, "options": {"delay": 0, "linkPreview": True}, "textMessage": {"text": texto}}
            return f"/message/sendText/{instancia}", corpo, None

        return self._tentar_destinos(destino, montar)

    def enviar_midia(self, instancia: str, destino: str, *, tipo: str, conteudo: bytes, mimetype: str, nome_arquivo: str, legenda: str = "") -> Resultado:
        b64 = base64.b64encode(conteudo).decode("ascii")
        tipo_evo = {"imagem": "image", "video": "video", "documento": "document", "figurinha": "image"}.get(tipo, "document")

        def montar(numero: str):
            if tipo == "audio":
                if self.versao.startswith("1"):
                    return f"/message/sendWhatsAppAudio/{instancia}", {"number": numero, "audioMessage": {"audio": b64}}, 40
                return f"/message/sendWhatsAppAudio/{instancia}", {"number": numero, "audio": b64}, 40
            if self.versao.startswith("1"):
                corpo = {"number": numero, "mediaMessage": {
                    "mediatype": tipo_evo, "caption": legenda, "media": b64, "fileName": nome_arquivo,
                }}
            else:
                corpo = {"number": numero, "mediatype": tipo_evo, "mimetype": mimetype, "caption": legenda, "media": b64, "fileName": nome_arquivo}
            return f"/message/sendMedia/{instancia}", corpo, 40

        return self._tentar_destinos(destino, montar)

    def apagar_para_todos(self, instancia: str, *, id_mensagem: str, remote_jid: str) -> Resultado:
        return self._requisicao(
            "DELETE", f"/chat/deleteMessageForEveryone/{instancia}",
            {"id": id_mensagem, "remoteJid": remote_jid, "fromMe": True, "participant": ""},
        )

    def baixar_midia(self, instancia: str, dados_mensagem: dict[str, Any]) -> tuple[bytes, str]:
        res = self._requisicao(
            "POST", f"/chat/getBase64FromMediaMessage/{instancia}",
            {"message": dados_mensagem, "convertToMp4": False}, timeout=40,
        )
        if not res.ok:
            raise EvolutionErro("Não foi possível baixar a mídia do WhatsApp.")
        b64 = str(res.dados.get("base64") or "").strip()
        if b64.startswith("data:") and "," in b64:
            b64 = b64.split(",", 1)[1]
        if not b64:
            raise EvolutionErro("O WhatsApp não devolveu o conteúdo da mídia.")
        return base64.b64decode(b64), str(res.dados.get("mimetype") or "")

    # -------------------------------------------------------------- instâncias
    def estado(self, instancia: str) -> dict[str, Any]:
        res = self._requisicao("GET", f"/instance/connectionState/{instancia}")
        if res.status_http == 404:
            return {"existe": False, "estado": "close"}
        if not res.ok:
            raise EvolutionErro(res.erro or "Falha ao consultar a conexão.")
        estado = (res.dados.get("instance") or {}).get("state") or res.dados.get("state") or "close"
        numero = ""
        if estado == "open":
            info = self._requisicao("GET", f"/instance/fetchInstances?instanceName={instancia}")
            lista = info.dados.get("lista") if info.ok else None
            registro = (lista[0] if isinstance(lista, list) and lista else info.dados) if info.ok else {}
            registro = registro.get("instance", registro) if isinstance(registro, dict) else {}
            numero = str(registro.get("owner") or registro.get("ownerJid") or "").split("@")[0]
        return {"existe": True, "estado": estado, "numero": numero}

    def criar(self, instancia: str) -> Resultado:
        corpo: dict[str, Any] = {"instanceName": instancia, "qrcode": True, "integration": "WHATSAPP-BAILEYS"}
        if self.versao.startswith("1"):
            corpo = {"instanceName": instancia, "qrcode": True}
        return self._requisicao("POST", "/instance/create", corpo)

    def conectar(self, instancia: str) -> dict[str, Any]:
        """Garante que a instância existe e devolve o QR Code em base64 (vazio se já conectada)."""
        situacao = self.estado(instancia)
        if situacao.get("estado") == "open":
            return {"estado": "open", "qrcode": "", "numero": situacao.get("numero", "")}
        if not situacao.get("existe"):
            criada = self.criar(instancia)
            if not criada.ok:
                raise EvolutionErro("A Evolution recusou a criação da instância.")
            qr = (criada.dados.get("qrcode") or {}).get("base64") or ""
            if qr:
                return {"estado": "connecting", "qrcode": qr}
        res = self._requisicao("GET", f"/instance/connect/{instancia}")
        if not res.ok:
            raise EvolutionErro("Não foi possível gerar o QR Code.")
        qr = res.dados.get("base64") or (res.dados.get("qrcode") or {}).get("base64") or ""
        return {"estado": "connecting" if qr else "close", "qrcode": qr, "codigo_pareamento": res.dados.get("pairingCode") or ""}

    def reiniciar(self, instancia: str) -> Resultado:
        return self._requisicao("PUT", f"/instance/restart/{instancia}")

    def desconectar(self, instancia: str) -> Resultado:
        return self._requisicao("DELETE", f"/instance/logout/{instancia}")

    def configurar_webhook(self, instancia: str) -> Resultado:
        url = url_webhook()
        segredo = getattr(settings, "EVOLUTION_WEBHOOK_SECRET", "")
        if self.versao.startswith("1"):
            corpo = {"enabled": True, "url": url, "webhook_by_events": False, "webhook_base64": False, "events": list(EVENTOS_WEBHOOK)}
        else:
            corpo = {"webhook": {
                "enabled": True, "url": url, "byEvents": False, "base64": False,
                "headers": {"X-Webhook-Token": segredo}, "events": list(EVENTOS_WEBHOOK),
            }}
        return self._requisicao("POST", f"/webhook/set/{instancia}", corpo)

    def consultar_webhook(self, instancia: str) -> dict[str, Any]:
        res = self._requisicao("GET", f"/webhook/find/{instancia}")
        dados = res.dados.get("webhook", res.dados) if res.ok else {}
        return dados if isinstance(dados, dict) else {}
