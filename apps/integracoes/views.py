from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.permissions import DevRequiredMixin
from apps.audit.services import record_audit

from . import cofre

GRUPOS = (
    ("stone", "Stone / Pagar.me", "fa-solid fa-credit-card"),
    ("umbler", "Umbler Talk (WhatsApp)", "fa-brands fa-whatsapp"),
)


class ChavesView(LoginRequiredMixin, DevRequiredMixin, View):
    """Página só de desenvolvedores para trocar as chaves da Stone e da Umbler sem mexer no .env.

    Os valores nunca voltam para a tela (nem depois de um erro): só origem e 4 últimos caracteres.
    """

    template_name = "integracoes/chaves.html"

    def get(self, request):
        return render(request, self.template_name, self._contexto())

    def post(self, request):
        trocas: dict[str, str] = {}
        remocoes: list[str] = []
        erros: dict[str, str] = {}
        for campo in cofre.CAMPOS:
            nome = campo.nome
            if request.POST.get(f"remover__{nome}"):
                remocoes.append(nome)
                continue
            texto = request.POST.get(f"valor__{nome}", "")
            if campo.gerar and request.POST.get(f"gerar__{nome}"):
                texto = cofre.gerar_segredo()
            if not texto.strip():
                continue
            try:
                trocas[nome] = cofre.validar(nome, texto)
            except cofre.ChaveInvalida as erro:
                erros[nome] = str(erro)

        if erros:
            messages.error(request, "Nada foi salvo. Corrija os campos marcados e envie de novo.")
            return render(request, self.template_name, self._contexto(erros), status=400)
        if not trocas and not remocoes:
            messages.info(request, "Nenhuma chave foi alterada.")
            return redirect("integracoes:chaves")

        with transaction.atomic():
            for nome, texto in trocas.items():
                cofre.salvar(nome, texto, request.user)
                record_audit(request.user, "chave_integracao.salva", "ChaveIntegracao",
                             after={"chave": cofre.nome_armazenado(nome), "final": cofre.final(texto)}, request=request)
            for nome in remocoes:
                if cofre.remover(nome):
                    record_audit(request.user, "chave_integracao.removida", "ChaveIntegracao",
                                 before={"chave": cofre.nome_armazenado(nome)}, request=request)

        partes = []
        if trocas:
            partes.append(f"{len(trocas)} chave(s) salva(s)")
        if remocoes:
            partes.append(f"{len(remocoes)} voltando a usar o .env")
        messages.success(request, "Pronto: " + " e ".join(partes) + ". Já vale para as próximas chamadas, sem reiniciar.")
        if "UMBLER_WEBHOOK_SECRET" in trocas or "UMBLER_WEBHOOK_SECRET" in remocoes:
            messages.warning(request, "O segredo do webhook da Umbler mudou: copie a nova URL em Chat > Números conectados "
                                      "e atualize o webhook no painel da Umbler.")
        return redirect("integracoes:chaves")

    def _contexto(self, erros: dict[str, str] | None = None) -> dict:
        erros = erros or {}
        grupos = []
        for chave, titulo, icone in GRUPOS:
            campos = []
            for campo in cofre.CAMPOS:
                if campo.grupo != chave:
                    continue
                campos.append({"campo": campo, "situacao": cofre.situacao(campo.nome), "erro": erros.get(campo.nome, "")})
            grupos.append({"chave": chave, "titulo": titulo, "icone": icone, "campos": campos})
        return {
            "grupos": grupos,
            "ambiente_stone": cofre.ambiente_stone(),
            "stone_em_producao": cofre.stone_em_producao(),
            "chave_mestra_propria": bool((getattr(settings, "INTEGRACOES_CHAVE_MESTRA", "") or "").strip()),
        }
