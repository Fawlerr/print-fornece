from django.contrib import admin

from .models import Charge


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = ("order", "provider", "type", "amount", "status", "created_at")
    list_filter = ("provider", "type", "status")

