from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, FormView, ListView, UpdateView

from apps.audit.services import record_audit

from .forms import (
    LoginForm,
    PrintFornecePasswordChangeForm,
    PrintFornecePasswordResetForm,
    ProfileForm,
    UserCreateForm,
    UserUpdateForm,
)
from .models import User
from .permissions import AdministratorRequiredMixin


def _login_rate_key(request: HttpRequest, email: str = "") -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    address = forwarded or request.META.get("REMOTE_ADDR", "unknown")
    return f"login-rate:{address}:{email.lower()}"


class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "")
        key = _login_rate_key(request, email)
        attempts = cache.get(key, 0)
        if attempts >= settings.LOGIN_RATE_LIMIT_ATTEMPTS:
            form = self.get_form()
            form.add_error(None, "Muitas tentativas. Aguarde alguns minutos e tente novamente.")
            return self.form_invalid(form)
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            cache.set(key, attempts + 1, getattr(settings, "LOGIN_RATE_LIMIT_WINDOW_SECONDS", getattr(settings, "LOGIN_RATE_LIMIT_SECONDS", 300)))
        return response

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        cache.delete(_login_rate_key(self.request, user.email))
        now = timezone.now()
        User.objects.filter(pk=user.pk).update(last_login=now, current_login_at=now, last_activity=now)
        record_audit(user, "login", "usuario", user.pk, request=self.request)
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, {self.request.get_host()}):
            return redirect(next_url)
        return redirect("accounts:change_password" if user.force_password_change else "home")


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        record_audit(request.user, "logout", "usuario", request.user.pk, request=request)
        User.objects.filter(pk=request.user.pk).update(current_login_at=None, last_activity=timezone.now())
    logout(request)
    return redirect("accounts:login")


class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        record_audit(self.request.user, "edicao_perfil", "usuario", self.request.user.pk, request=self.request)
        messages.success(self.request, "Nome atualizado com sucesso.")
        return response


class ChangePasswordView(LoginRequiredMixin, FormView):
    template_name = "accounts/change_password.html"
    form_class = PrintFornecePasswordChangeForm
    success_url = reverse_lazy("accounts:profile")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = form.save()
        user.force_password_change = False
        user.save(update_fields=["password", "force_password_change", "updated_at"])
        update_session_auth_hash(self.request, user)
        record_audit(user, "alteracao_senha", "usuario", user.pk, request=self.request)
        messages.success(self.request, "Senha atualizada com sucesso.")
        return super().form_valid(form)


class PasswordResetRequestView(auth_views.PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    form_class = PrintFornecePasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """A reset is an approved password change, so release the migration gate."""

    template_name = "registration/password_reset_confirm.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        self.user.force_password_change = False
        self.user.save(update_fields=["force_password_change", "updated_at"])
        return response


class UserListView(LoginRequiredMixin, AdministratorRequiredMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "users"

    def get_queryset(self):
        qs = User.objects.order_by("-is_active", "name")
        if not getattr(self.request.user, "is_dev", False):
            qs = qs.exclude(role=User.Role.DEV)
        return qs


class UserCreateView(LoginRequiredMixin, AdministratorRequiredMixin, CreateView):
    template_name = "accounts/user_form.html"
    form_class = UserCreateForm
    success_url = reverse_lazy("accounts:user_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["current_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        record_audit(self.request.user, "criacao", "usuario", self.object.pk, after={"email": self.object.email}, request=self.request)
        messages.success(self.request, "Usuário criado. Ele deverá trocar a senha no primeiro acesso.")
        return response


class UserUpdateView(LoginRequiredMixin, AdministratorRequiredMixin, UpdateView):
    template_name = "accounts/user_form.html"
    form_class = UserUpdateForm
    model = User
    success_url = reverse_lazy("accounts:user_list")

    def get_queryset(self):
        qs = super().get_queryset()
        if not getattr(self.request.user, "is_dev", False):
            qs = qs.exclude(role=User.Role.DEV)
        return qs

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["current_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        if self.object.pk == self.request.user.pk and not form.cleaned_data.get("is_active", True):
            form.add_error("is_active", "Você não pode desativar sua própria conta.")
            return self.form_invalid(form)
        remains_active_administrator = form.cleaned_data.get("role") in {User.Role.ADMINISTRATOR, User.Role.DEV} and form.cleaned_data.get("is_active", True)
        if self.object.is_administrator and self.object.is_active and not remains_active_administrator:
            if User.objects.filter(role__in=[User.Role.ADMINISTRATOR, User.Role.DEV], is_active=True).count() <= 1:
                form.add_error("role", "Mantenha ao menos um administrador ativo.")
                return self.form_invalid(form)
        response = super().form_valid(form)
        record_audit(self.request.user, "edicao", "usuario", self.object.pk, after={"email": self.object.email}, request=self.request)
        messages.success(self.request, "Usuário atualizado.")
        return response


def _format_relative_time(dt, now=None) -> str:
    if not dt:
        return "Nunca acessou"
    if not now:
        now = timezone.now()
    diff = int((now - dt).total_seconds())
    if diff < 0:
        return "Agora mesmo"
    if diff < 15:
        return "Agora mesmo"
    if diff < 60:
        return f"Há {diff}s atrás"
    if diff < 3600:
        mins = diff // 60
        return f"Há {mins} min atrás"
    if diff < 86400:
        hours = diff // 3600
        return f"Há {hours}h atrás"
    days = diff // 86400
    if days == 1:
        return "Ontem"
    return f"Há {days} dias atrás"


def _format_datetime(dt) -> str:
    if not dt:
        return "—"
    local_dt = timezone.localtime(dt)
    return local_dt.strftime("%d/%m/%Y às %H:%M:%S")


class OnlineUsersApiView(LoginRequiredMixin, View):
    """API endpoint providing real-time online users, live session stopwatch data, and last activity."""

    def get(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        now = timezone.now()

        if request.GET.get("heartbeat") == "1":
            User.objects.filter(pk=request.user.pk).update(last_activity=now)
            request.user.last_activity = now

        users_qs = User.objects.filter(is_active=True).order_by("name")
        if not getattr(request.user, "is_dev", False):
            users_qs = users_qs.exclude(role=User.Role.DEV)

        users_list = list(users_qs)

        users_data = []
        online_count = 0
        idle_count = 0

        for u in users_list:
            is_online = u.is_online
            is_idle = u.is_idle
            if is_online:
                online_count += 1
                status = "online"
                status_label = "Online"
            elif is_idle:
                idle_count += 1
                status = "idle"
                status_label = "Ausente"
            else:
                status = "offline"
                status_label = "Desconectado"

            online_sec = u.online_duration_seconds if (is_online or is_idle) else 0

            users_data.append({
                "id": u.pk,
                "name": u.name or u.email,
                "email": u.email,
                "role": u.role,
                "role_label": u.get_role_display(),
                "sector": u.sector,
                "sector_label": u.get_sector_display(),
                "is_online": is_online,
                "is_idle": is_idle,
                "status": status,
                "status_label": status_label,
                "online_seconds": online_sec,
                "current_login_at": u.current_login_at.isoformat() if u.current_login_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "last_login_formatted": _format_datetime(u.last_login or u.current_login_at),
                "last_activity": u.last_activity.isoformat() if u.last_activity else None,
                "last_activity_formatted": _format_datetime(u.last_activity),
                "last_activity_relative": _format_relative_time(u.last_activity, now),
                "last_seen_page": u.last_seen_page or "—",
                "last_seen_device": u.last_seen_device or "—",
                "is_self": (u.pk == request.user.pk),
            })

        def sort_key(item):
            status_priority = {"online": 0, "idle": 1, "offline": 2}
            return (status_priority.get(item["status"], 3), -(item["online_seconds"] or 0), item["name"])

        users_data.sort(key=sort_key)

        return JsonResponse({
            "online_count": online_count,
            "idle_count": idle_count,
            "total_users": len(users_data),
            "users": users_data,
            "server_time": now.isoformat(),
        })

    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        return self.get(request, *args, **kwargs)

