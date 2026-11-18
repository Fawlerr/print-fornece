"""Camada de provedor: o serviço do chat fala só com estes adaptadores.

- ``umbler`` (padrão): Umbler Talk, API oficial com token (``apps.whatsapp.umbler``).
- ``evolution``: Evolution API, mantida como alternativa (``apps.whatsapp.evolution``).

Todos devolvem ``Envio`` e levantam ``ProvedorErro`` com mensagem pronta para a equipe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .evolution import EvolutionClient, EvolutionErro
from .models import Instancia
from .umbler import ESTADOS_CANAL, ESTADOS_MENSAGEM, UmblerClient, UmblerErro, campo


class ProvedorErro(RuntimeError):
    pass


@dataclass
class Envio:
    ok: bool
    id_mensagem: str = ""
    remote_jid: str = ""
    status: str = ""  # status do Print já traduzido, quando o provedor informa
    erro: str = ""


def _limite_midia() -> int:
    return int(getattr(settings, "WHATSAPP_MAX_UPLOAD_MB", 16)) * 1024 * 1024 * 4


class ProvedorEvolution:
    nome = Instancia.Provedor.EVOLUTION
    apaga_para_todos = True

    def __init__(self, instancia: Instancia):
        self.instancia = instancia
        self.cliente = EvolutionClient()

    def _envio(self, resultado) -> Envio:
        return Envio(resultado.ok, resultado.id_mensagem, resultado.remote_jid, "enviada" if resultado.ok else "falhou", resultado.erro)

    def enviar_texto(self, destino: str, texto: str, *, nome_contato: str = "") -> Envio:
        try:
            return self._envio(self.cliente.enviar_texto(self.instancia.nome, destino, texto))
        except EvolutionErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def enviar_midia(self, destino: str, *, tipo: str, conteudo: bytes, mimetype: str, nome_arquivo: str, legenda: str = "") -> Envio:
        try:
            return self._envio(self.cliente.enviar_midia(
                self.instancia.nome, destino, tipo=tipo, conteudo=conteudo, mimetype=mimetype, nome_arquivo=nome_arquivo, legenda=legenda,
            ))
        except EvolutionErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def apagar_para_todos(self, *, id_mensagem: str, remote_jid: str) -> bool:
        try:
            return self.cliente.apagar_para_todos(self.instancia.nome, id_mensagem=id_mensagem, remote_jid=remote_jid).ok
        except EvolutionErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def baixar_midia(self, dados: dict[str, Any]) -> tuple[bytes, str, str]:
        try:
            conteudo, mimetype = self.cliente.baixar_midia(self.instancia.nome, dados)
        except EvolutionErro as exc:
            raise ProvedorErro(str(exc)) from exc
        return conteudo, mimetype, ""

    def status_mensagem(self, id_mensagem: str) -> str:
        return ""  # a Evolution informa status pelo webhook (messages.update)


class ProvedorUmbler:
    nome = Instancia.Provedor.UMBLER
    apaga_para_todos = True

    def __init__(self, instancia: Instancia):
        self.instancia = instancia
        self.cliente = UmblerClient()

    def _origem(self) -> str:
        if not self.instancia.telefone_canal:
            raise ProvedorErro("Este número da Umbler está sem o telefone do canal. Importe os canais em Números conectados.")
        return self.instancia.telefone_canal

    @staticmethod
    def _envio(resposta) -> Envio:
        if not resposta.ok:
            return Envio(False, erro=resposta.erro or "A Umbler recusou a mensagem.")
        dados = resposta.dados if isinstance(resposta.dados, dict) else {}
        estado = str(campo(dados, "messageState") or "").lower()
        status = ESTADOS_MENSAGEM.get(estado, "enviada")
        return Envio(status != "falhou", str(campo(dados, "id") or ""), "", status, "A Umbler marcou a mensagem como falha." if status == "falhou" else "")

    def enviar_texto(self, destino: str, texto: str, *, nome_contato: str = "") -> Envio:
        if "@lid" in destino:
            raise ProvedorErro("Este contato ainda não tem número conhecido; responda pela Umbler.")
        try:
            return self._envio(self.cliente.enviar_texto(de=self._origem(), para=destino, texto=texto, nome_contato=nome_contato))
        except UmblerErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def enviar_midia(self, destino: str, *, tipo: str, conteudo: bytes, mimetype: str, nome_arquivo: str, legenda: str = "") -> Envio:
        if "@lid" in destino:
            raise ProvedorErro("Este contato ainda não tem número conhecido; responda pela Umbler.")
        try:
            return self._envio(self.cliente.enviar_arquivo(
                de=self._origem(), para=destino, conteudo=conteudo, nome_arquivo=nome_arquivo, mimetype=mimetype, legenda=legenda,
            ))
        except UmblerErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def apagar_para_todos(self, *, id_mensagem: str, remote_jid: str) -> bool:
        try:
            return self.cliente.apagar(id_mensagem, para_todos=True).ok
        except UmblerErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def baixar_midia(self, dados: dict[str, Any]) -> tuple[bytes, str, str]:
        id_mensagem = str((dados or {}).get("umbler_id") or "")
        if not id_mensagem:
            raise ProvedorErro("Mensagem sem referência de mídia na Umbler.")
        try:
            return self.cliente.baixar_arquivo_da_mensagem(id_mensagem, _limite_midia())
        except UmblerErro as exc:
            raise ProvedorErro(str(exc)) from exc

    def status_mensagem(self, id_mensagem: str) -> str:
        """Status atual (a Umbler ainda não manda webhook de status). '' = não deu para consultar."""
        try:
            res = self.cliente.mensagem(id_mensagem)
        except UmblerErro:
            return ""
        if not res.ok or not isinstance(res.dados, dict):
            return ""
        estado = str(campo(res.dados, "messageState") or "").lower()
        if estado == "deleted":
            return "revogada"
        return ESTADOS_MENSAGEM.get(estado, "")

    def estado_canal(self) -> dict[str, str]:
        if not self.instancia.canal_id:
            raise ProvedorErro("Informe o ID do canal da Umbler (ou importe os canais).")
        try:
            canal = self.cliente.canal(self.instancia.canal_id)
        except UmblerErro as exc:
            raise ProvedorErro(str(exc)) from exc
        estado_bruto = str(campo(canal, "state") or "").lower()
        return {"estado": ESTADOS_CANAL.get(estado_bruto, "close"), "numero": str(campo(canal, "phoneNumber") or "").lstrip("+")}


def provedor_para(instancia: Instancia):
    if instancia.provedor == Instancia.Provedor.EVOLUTION:
        return ProvedorEvolution(instancia)
    return ProvedorUmbler(instancia)
