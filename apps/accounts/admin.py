from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import SystemSetting, User


@admin.register(User)
class PrintForneceUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "name", "role", "is_active", "is_staff")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados", {"fields": ("name", "role", "force_password_change")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Datas", {"fields": ("last_login", "date_joined", "updated_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "name", "role", "password1", "password2")}),)
    search_fields = ("email", "name")
    readonly_fields = ("date_joined", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not getattr(request.user, "is_dev", False):
            qs = qs.exclude(role=User.Role.DEV)
        return qs


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "status_badge", "is_active", "action_button", "updated_at")
    list_editable = ("is_active",)
    search_fields = ("name", "key", "description")
    readonly_fields = ("updated_at",)
    actions = ["enable_features", "disable_features"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        if obj.is_active:
            return mark_safe('<span style="background: rgba(34, 197, 94, 0.15); color: #16a34a; border: 1px solid #16a34a; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 0.8rem;">● LIBERADO</span>')
        return mark_safe('<span style="background: rgba(239, 68, 68, 0.15); color: #dc2626; border: 1px solid #dc2626; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 0.8rem;">● BLOQUEADO</span>')

    @admin.display(description="Ação Rápida (1 Clique)")
    def action_button(self, obj):
        toggle_url = reverse("admin:accounts_systemsetting_toggle", args=[obj.pk])
        if obj.is_active:
            return format_html(
                '<a class="button" style="background: #dc2626; color: #ffffff; padding: 4px 10px; border-radius: 4px; font-weight: 600; text-decoration: none;" href="{}">🔒 Bloquear Agora</a>',
                toggle_url,
            )
        return format_html(
            '<a class="button" style="background: #16a34a; color: #ffffff; padding: 4px 10px; border-radius: 4px; font-weight: 600; text-decoration: none;" href="{}">🔓 Desbloquear Agora</a>',
            toggle_url,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:setting_id>/toggle/",
                self.admin_site.admin_view(self.toggle_view),
                name="accounts_systemsetting_toggle",
            ),
        ]
        return custom_urls + urls

    def toggle_view(self, request, setting_id):
        setting = get_object_or_404(SystemSetting, pk=setting_id)
        setting.is_active = not setting.is_active
        setting.save(update_fields=["is_active", "updated_at"])
        status_txt = "DESBLOQUEADA / LIBERADA" if setting.is_active else "BLOQUEADA"
        self.message_user(
            request,
            f"Funcionalidade '{setting.name}' agora está {status_txt}.",
            messages.SUCCESS,
        )
        return redirect(reverse("admin:accounts_systemsetting_changelist"))

    @admin.action(description="🔓 Desbloquear funcionalidades selecionadas")
    def enable_features(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} funcionalidade(s) desbloqueada(s) com sucesso.", messages.SUCCESS)

    @admin.action(description="🔒 Bloquear funcionalidades selecionadas")
    def disable_features(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} funcionalidade(s) bloqueada(s) com sucesso.", messages.WARNING)


