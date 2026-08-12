from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
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
            cache.set(key, attempts + 1, settings.LOGIN_RATE_LIMIT_SECONDS)
        return response

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        cache.delete(_login_rate_key(self.request, user.email))
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        record_audit(user, "login", "usuario", user.pk, request=self.request)
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, {self.request.get_host()}):
            return redirect(next_url)
        return redirect("accounts:change_password" if user.force_password_change else "home")


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        record_audit(request.user, "logout", "usuario", request.user.pk, request=request)
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
