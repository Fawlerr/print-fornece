from django.contrib import admin

from .models import BusinessSettings


@admin.register(BusinessSettings)
class BusinessSettingsAdmin(admin.ModelAdmin):
    """Somente leitura no Django Admin: a edição acontece na tela própria (/configuracoes/)."""

    exclude = ("cancellation_pin_hash",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
