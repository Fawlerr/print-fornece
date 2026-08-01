from django.contrib import admin

from .models import Order, OrderAttachment, OrderHistory, OrderNote, OrderStageHistory


class AttachmentInline(admin.TabularInline):
    model = OrderAttachment
    extra = 0
    readonly_fields = ("original_name", "content_type", "size", "created_at")


class HistoryInline(admin.TabularInline):
    model = OrderHistory
    extra = 0
    readonly_fields = ("user", "action", "description", "created_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "client_name", "stage", "payment_status", "total_amount", "responsible", "created_at")
    list_filter = ("stage", "payment_status", "priority")
    search_fields = ("number", "client_name", "client_whatsapp")
    list_select_related = ("responsible", "created_by")
    inlines = (AttachmentInline, HistoryInline)


admin.site.register(OrderNote)
admin.site.register(OrderStageHistory)

