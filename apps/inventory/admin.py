from django.contrib import admin

from .models import SupplyItem, SupplyMovement


@admin.register(SupplyItem)
class SupplyItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "quantity", "unit", "minimum_quantity", "updated_at")
    list_filter = ("category", "unit")
    search_fields = ("name", "notes")


@admin.register(SupplyMovement)
class SupplyMovementAdmin(admin.ModelAdmin):
    list_display = ("item", "movement_type", "quantity", "previous_quantity", "new_quantity", "user", "created_at")
    list_filter = ("movement_type", "created_at")
    search_fields = ("item__name", "description", "user__name", "user__email")
