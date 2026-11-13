from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms.models import model_to_dict
from django.shortcuts import redirect, render

from apps.accounts.permissions import require_administrator
from apps.audit.services import record_audit

from .forms import ShirtDiscountSettingsForm
from .models import BusinessSettings

# Campos sensíveis nunca vão para a auditoria (nem em hash).
SENSITIVE_FIELDS = {"cancellation_pin_hash"}

# Cada seção da tela é um formulário independente, salvo por um botão próprio.
SECTION_FORMS = {
    "desconto_camisa": ShirtDiscountSettingsForm,
}


def _audit_snapshot(config: BusinessSettings) -> dict:
    data = model_to_dict(config)
    return {key: str(value) for key, value in data.items() if key not in SENSITIVE_FIELDS}


def _build_forms(config: BusinessSettings, bound_section: str | None = None, data=None) -> dict:
    forms = {}
    for key, form_class in SECTION_FORMS.items():
        if key == bound_section:
            forms[key] = form_class(data, instance=config, prefix=key)
        else:
            forms[key] = form_class(instance=config, prefix=key)
    return forms


@login_required
def settings_view(request):
    """Tela de configurações do negócio — somente administradores e dev."""
    require_administrator(request.user)
    config = BusinessSettings.load()

    section = request.POST.get("section") if request.method == "POST" else None
    if section and section not in SECTION_FORMS:
        messages.error(request, "Seção de configuração inválida.")
        return redirect("business:settings")

    forms = _build_forms(config, section, request.POST if section else None)
    if section:
        form = forms[section]
        if form.is_valid():
            before = _audit_snapshot(config)
            with transaction.atomic():
                updated = form.save(commit=False)
                updated.updated_by = request.user
                updated.save()
                record_audit(request.user, "configuracoes_alteradas", "configuracoes", updated.pk, before=before, after=_audit_snapshot(updated), request=request)
            messages.success(request, "Configurações salvas.")
            return redirect(f"{request.path}#{section}")
        messages.error(request, "Revise os campos destacados.")

    return render(request, "business/settings.html", {"config": config, "forms": forms})
