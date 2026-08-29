from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone


def _detect_device(user_agent: str) -> str:
    ua = user_agent.lower()
    is_mobile = "mobile" in ua or "android" in ua or "iphone" in ua or "ipad" in ua
    
    if "iphone" in ua or "ipad" in ua:
        browser = "Safari" if "safari" in ua and "crios" not in ua else "Chrome"
        return f"Mobile · iOS ({browser})"
    elif "android" in ua:
        return "Mobile · Android"
    elif is_mobile:
        return "Mobile"
    elif "windows" in ua:
        browser = "Edge" if "edg" in ua else ("Chrome" if "chrome" in ua else "Firefox" if "firefox" in ua else "Navegador")
        return f"Desktop · Windows ({browser})"
    elif "macintosh" in ua or "mac os" in ua:
        return "Desktop · Mac"
    elif "linux" in ua:
        return "Desktop · Linux"
    return "Desktop"


def _get_page_name(path: str) -> str:
    path_clean = path.rstrip("/") or "/"
    
    if path_clean in {"", "/"}:
        return "Visão Geral"
    elif "/orders/new" in path_clean or "/orders/create" in path_clean:
        return "Novo Pedido"
    elif path_clean.startswith("/orders"):
        return "Gestão de Pedidos"
    elif path_clean == "/production" or path_clean == "/production/kanban":
        return "Produção Kanban"
    elif path_clean.startswith("/production"):
        return "Detalhes de Produção"
    elif "/caixa" in path_clean:
        return "Fechamento de Caixa"
    elif "/reports/production" in path_clean:
        return "Relatório de Metros DTF"
    elif path_clean.startswith("/reports"):
        return "Relatórios Gerenciais"
    elif path_clean.startswith("/payments"):
        return "Gestão de Clientes"
    elif path_clean.startswith("/inventory"):
        return "Estoque de Insumos"
    elif path_clean.startswith("/expenses"):
        return "Despesas"
    elif path_clean.startswith("/backups"):
        return "Backups do Sistema"
    elif path_clean.startswith("/notifications"):
        return "Central de Notificações"
    elif path_clean.startswith("/bug-reports"):
        return "Relatos de Bug"
    elif path_clean.startswith("/accounts/users"):
        return "Gestão de Usuários"
    elif path_clean.startswith("/accounts/profile"):
        return "Meu Perfil"
    return path_clean[:50]


class UserActivityMiddleware:
    """Track active online users, session duration, last seen page and device."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            path = request.path
            # Ignorar arquivos estáticos, mídias e endpoints de polling em background
            ignored_prefixes = (
                "/static/",
                "/media/",
                "/favicon.ico",
                "/health/",
                "/notifications/poll",
                "/accounts/online-users",
            )
            if not any(path.startswith(prefix) for prefix in ignored_prefixes):
                now = timezone.now()
                last_act = getattr(user, "last_activity", None)
                cur_login = getattr(user, "current_login_at", None)

                # Atualizar a cada 25 segundos ou se ainda não tiver registro de atividade/sessão
                if not last_act or not cur_login or (now - last_act).total_seconds() >= 25:
                    from apps.accounts.models import User
                    device = _detect_device(request.META.get("HTTP_USER_AGENT", ""))
                    page = _get_page_name(path)
                    
                    update_fields = {
                        "last_activity": now,
                        "last_seen_page": page,
                        "last_seen_device": device,
                    }
                    if not cur_login:
                        update_fields["current_login_at"] = getattr(user, "last_login", None) or now
                    
                    User.objects.filter(pk=user.pk).update(**update_fields)
                    user.last_activity = now
                    if not cur_login:
                        user.current_login_at = update_fields.get("current_login_at")
                    user.last_seen_page = page
                    user.last_seen_device = device

        return self.get_response(request)


class ForcePasswordChangeMiddleware:
    """Keep imported/demo accounts on the password screen until they set a new password."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.force_password_change:
            allowed = {
                reverse("accounts:change_password"),
                reverse("accounts:logout"),
            }
            if request.path not in allowed and not request.path.startswith("/admin/"):
                return redirect("accounts:change_password")
        return self.get_response(request)


