from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.accounts.permissions import AdministratorRequiredMixin
from apps.expenses.models import Expense
from apps.orders.models import Order, OrderStageHistory

from .forms import ReportFilterForm


class ReportView(LoginRequiredMixin, AdministratorRequiredMixin, TemplateView):
    template_name = "reports/index.html"

    def _filters(self):
        initial = {"start": timezone.localdate().replace(day=1), "end": timezone.localdate()}
        form = ReportFilterForm(self.request.GET or None, initial=initial)
        form.is_valid()
        data = form.cleaned_data if form.is_bound and form.is_valid() else initial
        start = data.get("start") or initial["start"]
        end = data.get("end") or initial["end"]
        if end < start:
            start, end = end, start
        return form, data, start, end

    def _orders(self, data, start, end):
        start_at = timezone.make_aware(datetime.combine(start, time.min))
        end_at = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
        queryset = Order.objects.select_related("responsible").prefetch_related(
            Prefetch("stage_history", queryset=OrderStageHistory.objects.order_by("created_at", "pk"))
        ).filter(created_at__gte=start_at, created_at__lt=end_at).order_by("-created_at", "-pk")
        for field in ("stage", "payment_status", "priority"):
            if data.get(field):
                queryset = queryset.filter(**{field: data[field]})
        if data.get("responsible"):
            queryset = queryset.filter(responsible_id=data["responsible"])
        return queryset

    @staticmethod
    def _stage_durations(orders):
        totals = defaultdict(lambda: Decimal("0"))
        counts = defaultdict(int)
        now = timezone.now()
        for order in orders:
            history = list(order.stage_history.all())
            for index, item in enumerate(history):
                next_at = history[index + 1].created_at if index + 1 < len(history) else now
                if item.new_stage in {Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT, Order.Stage.PAYMENT_CONFIRMED, Order.Stage.PRE_PRESS, Order.Stage.PRODUCTION, Order.Stage.READY} and next_at >= item.created_at:
                    totals[item.new_stage] += Decimal(str((next_at - item.created_at).total_seconds() / 3600))
                    counts[item.new_stage] += 1
        active_stages = (Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT, Order.Stage.PAYMENT_CONFIRMED, Order.Stage.PRE_PRESS, Order.Stage.PRODUCTION, Order.Stage.READY)
        return {stage: (round(totals[stage] / counts[stage], 1) if counts[stage] else None) for stage in active_stages}

    def get(self, request, *args, **kwargs):
        form, data, start, end = self._filters()
        orders = list(self._orders(data, start, end))
        if request.GET.get("export") == "csv":
            return self._csv_response(orders)
        active = [order for order in orders if order.stage != Order.Stage.CANCELLED]
        paid = sum((order.paid_amount for order in active), Decimal("0"))
        pending = sum((max(Decimal("0"), order.total_amount - order.paid_amount) for order in active), Decimal("0"))
        completed = sum(order.stage in (Order.Stage.DELIVERED, "finalizado") for order in orders)
        cancelled = sum(order.stage == Order.Stage.CANCELLED for order in orders)
        ticket = sum((order.total_amount for order in active), Decimal("0")) / len(active) if active else Decimal("0")
        expenses = Expense.objects.filter(status=Expense.Status.ACTIVE, expense_date__range=(start, end)).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        context = self.get_context_data(
            filter_form=form,
            orders=orders,
            users=User.objects.filter(is_active=True).only("id", "name").order_by("name"),
            paid=paid,
            pending=pending,
            expenses=expenses,
            profit=paid - expenses,
            ticket=ticket,
            completed=completed,
            cancelled=cancelled,
            stage_durations=self._stage_durations(orders),
            order_count=len(orders),
        )
        return self.render_to_response(context)

    @staticmethod
    def _csv_response(orders):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="relatorio-print-fornece-{timezone.localdate():%Y%m%d}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Número", "Cliente", "WhatsApp", "Valor total", "Valor pago", "Pagamento", "Etapa", "Prioridade", "Responsável", "Criado em"])
        for order in orders:
            writer.writerow([
                order.number, order.client_name, order.client_whatsapp, f"{order.total_amount:.2f}".replace(".", ","),
                f"{order.paid_amount:.2f}".replace(".", ","), order.get_payment_status_display(), order.get_stage_display(),
                order.get_priority_display(), order.responsible.name if order.responsible_id else "", timezone.localtime(order.created_at).strftime("%d/%m/%Y %H:%M"),
            ])
        return response

