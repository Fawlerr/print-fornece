from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.permissions import AdministratorRequiredMixin
from apps.expenses.models import Expense
from apps.orders.models import Order, OrderHistory


@login_required
def home(request):
    return redirect("dashboard:index" if request.user.is_administrator else "production:kanban")


class DashboardView(LoginRequiredMixin, AdministratorRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.localtime()
        today_start = timezone.make_aware(datetime.combine(now.date(), time.min))
        tomorrow_start = today_start + timedelta(days=1)
        month_start = today_start.replace(day=1)
        next_month_start = (month_start + timedelta(days=32)).replace(day=1)
        trend_start = today_start - timedelta(days=6)
        idle_cutoff = now - timedelta(hours=48)

        orders = Order.objects.all()
        money_field = DecimalField(max_digits=12, decimal_places=2)
        money_zero = Value(Decimal("0"), output_field=money_field)
        stats = orders.aggregate(
            revenue_today=Coalesce(Sum("total_amount", filter=Q(payment_status=Order.PaymentStatus.PAID, created_at__gte=today_start, created_at__lt=tomorrow_start) & ~Q(stage=Order.Stage.CANCELLED)), money_zero, output_field=money_field),
            revenue_month=Coalesce(Sum("total_amount", filter=Q(payment_status=Order.PaymentStatus.PAID, created_at__gte=month_start, created_at__lt=next_month_start) & ~Q(stage=Order.Stage.CANCELLED)), money_zero, output_field=money_field),
            orders_today=Count("pk", filter=Q(created_at__gte=today_start, created_at__lt=tomorrow_start)),
            in_progress=Count("pk", filter=Q(stage__in=[Order.Stage.PREPARATION, Order.Stage.PRODUCTION])),
            ready=Count("pk", filter=Q(stage=Order.Stage.READY)),
            awaiting_payment=Count("pk", filter=~Q(payment_status=Order.PaymentStatus.PAID) & ~Q(stage__in=[Order.Stage.CANCELLED, Order.Stage.FINISHED])),
            stage_new=Count("pk", filter=Q(stage=Order.Stage.NEW)),
            stage_preparation=Count("pk", filter=Q(stage=Order.Stage.PREPARATION)),
            stage_production=Count("pk", filter=Q(stage=Order.Stage.PRODUCTION)),
            stage_ready=Count("pk", filter=Q(stage=Order.Stage.READY)),
        )
        expenses_month = Expense.objects.filter(status=Expense.Status.ACTIVE, expense_date__gte=month_start.date(), expense_date__lt=next_month_start.date()).aggregate(total=Coalesce(Sum("amount"), money_zero, output_field=money_field))["total"]

        revenue_rows = orders.filter(created_at__gte=trend_start, created_at__lt=tomorrow_start).annotate(day=TruncDate("created_at")).values("day").annotate(
            total=Coalesce(Sum("total_amount", filter=Q(payment_status=Order.PaymentStatus.PAID) & ~Q(stage=Order.Stage.CANCELLED)), money_zero, output_field=money_field)
        )
        expense_rows = Expense.objects.filter(status=Expense.Status.ACTIVE, expense_date__gte=trend_start.date(), expense_date__lt=tomorrow_start.date()).values("expense_date").annotate(total=Coalesce(Sum("amount"), money_zero, output_field=money_field))
        revenue_by_day = {str(row["day"]): float(row["total"]) for row in revenue_rows}
        expenses_by_day = {str(row["expense_date"]): float(row["total"]) for row in expense_rows}
        days = [trend_start.date() + timedelta(days=index) for index in range(7)]

        context.update({
            "stats": stats,
            "expenses_month": expenses_month,
            "monthly_profit": stats["revenue_month"] - expenses_month,
            "recent_orders": orders.select_related("responsible").order_by("-created_at", "-pk")[:7],
            "late_orders": orders.filter(stage__in=[Order.Stage.NEW, Order.Stage.PREPARATION, Order.Stage.PRODUCTION]).filter(Q(due_at__lt=now) | Q(stage_updated_at__lt=idle_cutoff)).order_by("due_at", "stage_updated_at")[:8],
            "movements": OrderHistory.objects.select_related("order", "user").order_by("-created_at", "-pk")[:7],
            "chart_labels": [day.strftime("%d/%m") for day in days],
            "chart_revenue": [revenue_by_day.get(str(day), 0) for day in days],
            "chart_expenses": [expenses_by_day.get(str(day), 0) for day in days],
            "stage_stats": [stats["stage_new"], stats["stage_preparation"], stats["stage_production"], stats["stage_ready"]],
            # Kept deliberately equal to the legacy dashboard: it counts fully
            # paid order totals, while reports expose actual paid_amount.
            "dashboard_finance_note": "O dashboard mantém a regra histórica: faturamento considera pedidos integralmente pagos.",
        })
        return context
