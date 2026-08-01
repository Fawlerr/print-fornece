from django.contrib import admin

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "category", "amount", "expense_date", "status", "created_by")
    list_filter = ("status", "category")
    search_fields = ("description",)
    list_select_related = ("created_by", "cancelled_by")

