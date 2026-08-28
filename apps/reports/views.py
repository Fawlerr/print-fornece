from __future__ import annotations

import calendar
import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.accounts.permissions import AdministratorRequiredMixin
from apps.expenses.models import Expense
from apps.orders.models import Order, OrderItem, OrderStageHistory

from .forms import ProductionReportFilterForm, ReportFilterForm


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


class ProductionReportView(LoginRequiredMixin, AdministratorRequiredMixin, TemplateView):
    template_name = "reports/production.html"

    def _parse_month(self, month_str: str | None) -> tuple[int, int, date, date]:
        today = timezone.localdate()
        year = today.year
        month = today.month
        if month_str:
            try:
                parts = month_str.strip().split("-")
                if len(parts) == 2:
                    y, m = int(parts[0]), int(parts[1])
                    if 2000 <= y <= 2100 and 1 <= m <= 12:
                        year, month = y, m
            except (ValueError, TypeError):
                pass
        
        _, num_days = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)
        return year, month, start_date, end_date

    def get(self, request, *args, **kwargs):
        month_param = request.GET.get("month") or timezone.localdate().strftime("%Y-%m")
        year, month, start_date, end_date = self._parse_month(month_param)
        responsible_id = request.GET.get("responsible")
        material_type = request.GET.get("material_type") or ""

        form = ProductionReportFilterForm(initial={
            "month": f"{year:04d}-{month:02d}",
            "responsible": responsible_id,
            "material_type": material_type,
        }, data=request.GET or None)

        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min))

        orders_qs = Order.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        ).exclude(
            stage=Order.Stage.CANCELLED
        ).select_related("responsible", "created_by").prefetch_related("items")

        if responsible_id:
            try:
                resp_pk = int(responsible_id)
                orders_qs = orders_qs.filter(Q(responsible_id=resp_pk) | Q(created_by_id=resp_pk))
            except (ValueError, TypeError):
                pass

        orders = list(orders_qs.order_by("created_at", "pk"))

        # Daily breakdown structure for all days in month
        days_map: dict[date, dict[str, object]] = {}
        curr = start_date
        while curr <= end_date:
            days_map[curr] = {
                "date": curr,
                "day_num": curr.day,
                "weekday": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][curr.weekday()],
                "textil_meters": Decimal("0.00"),
                "uv_meters": Decimal("0.00"),
                "total_meters": Decimal("0.00"),
                "orders_count": 0,
                "orders_list": [],
            }
            curr += timedelta(days=1)

        total_orders_set = set()

        for order in orders:
            order_date = timezone.localtime(order.created_at).date()
            if order_date not in days_map:
                continue

            order_items = list(order.items.all())
            order_has_dtf = False

            for item in order_items:
                mat_code = (item.material_code or "").lower()
                mat_name = (item.material_name or "").lower()
                kind = getattr(item, "kind", "")

                is_uv = ("uv" in mat_code or "uv" in mat_name)
                is_textil = (mat_code == "dtf_textil" or (kind == "material" and not is_uv))

                # Check material filter
                if material_type == "dtf_textil" and not is_textil:
                    continue
                if material_type == "dtf_uv" and not is_uv:
                    continue

                meters = Decimal("0.00")
                if item.calculation_snapshot and "film_used_m" in item.calculation_snapshot:
                    meters = Decimal(str(item.calculation_snapshot["film_used_m"]))
                elif "metro" in (item.billing_unit or "").lower():
                    meters = Decimal(str(item.billing_quantity))
                elif item.used_length_cm:
                    meters = Decimal(str(item.used_length_cm)) / Decimal("100")

                if meters > Decimal("0.00"):
                    order_has_dtf = True
                    if is_uv:
                        days_map[order_date]["uv_meters"] += meters
                    else:
                        days_map[order_date]["textil_meters"] += meters
                    days_map[order_date]["total_meters"] += meters

            if order_has_dtf:
                days_map[order_date]["orders_count"] += 1
                days_map[order_date]["orders_list"].append(order)
                total_orders_set.add(order.id)

        daily_rows = list(days_map.values())

        # Totals and KPIs
        total_textil = sum((r["textil_meters"] for r in daily_rows), Decimal("0.00"))
        total_uv = sum((r["uv_meters"] for r in daily_rows), Decimal("0.00"))
        total_meters = total_textil + total_uv
        active_days = sum(1 for r in daily_rows if r["total_meters"] > Decimal("0.00"))
        avg_daily = (total_meters / Decimal(str(active_days))) if active_days > 0 else Decimal("0.00")
        
        peak_row = max(daily_rows, key=lambda r: r["total_meters"], default=None)
        peak_meters = peak_row["total_meters"] if peak_row else Decimal("0.00")
        peak_date = peak_row["date"] if peak_row and peak_meters > 0 else None

        if request.GET.get("export") == "csv":
            return self._csv_export(daily_rows, year, month)

        # Meses para navegação
        prev_month_date = start_date - timedelta(days=1)
        next_month_date = end_date + timedelta(days=1)
        prev_month_str = prev_month_date.strftime("%Y-%m")
        next_month_str = next_month_date.strftime("%Y-%m")

        month_names = [
            "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
        ]
        month_label = f"{month_names[month]} de {year}"

        context = self.get_context_data(
            form=form,
            year=year,
            month=month,
            month_label=month_label,
            current_month_str=f"{year:04d}-{month:02d}",
            prev_month_str=prev_month_str,
            next_month_str=next_month_str,
            users=User.objects.filter(is_active=True).only("id", "name").order_by("name"),
            daily_rows=daily_rows,
            total_textil=total_textil,
            total_uv=total_uv,
            total_meters=total_meters,
            active_days=active_days,
            avg_daily=avg_daily,
            peak_meters=peak_meters,
            peak_date=peak_date,
            total_orders_count=len(total_orders_set),
            responsible_id=responsible_id,
            material_type=material_type,
        )
        return self.render_to_response(context)

    @staticmethod
    def _csv_export(daily_rows, year, month):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="relatorio-producao-metros-{year:04d}{month:02d}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Data", "Dia da Semana", "DTF Têxtil (m)", "DTF UV (m)", "Total de Metros (m)", "Qtd. Pedidos", "Números dos Pedidos"])
        for r in daily_rows:
            date_str = r["date"].strftime("%d/%m/%Y")
            orders_str = ", ".join(o.number for o in r["orders_list"])
            writer.writerow([
                date_str,
                r["weekday"],
                f"{r['textil_meters']:.2f}".replace(".", ","),
                f"{r['uv_meters']:.2f}".replace(".", ","),
                f"{r['total_meters']:.2f}".replace(".", ","),
                r["orders_count"],
                orders_str,
            ])
        return response


class CashRegisterReportView(LoginRequiredMixin, AdministratorRequiredMixin, TemplateView):
    template_name = "reports/cash_register.html"

    def get_target_date(self) -> date:
        date_str = self.request.GET.get("date", "").strip()
        if date_str:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                pass
        return timezone.localdate()

    def get(self, request, *args, **kwargs):
        target_date = self.get_target_date()
        today = timezone.localdate()

        start_dt = timezone.make_aware(datetime.combine(target_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(target_date, time.max))

        # Pedidos com recebimento na data selecionada
        orders = Order.objects.filter(
            (
                Q(payment_confirmed_at__gte=start_dt, payment_confirmed_at__lte=end_dt) |
                Q(payment_confirmed_at__isnull=True, created_at__gte=start_dt, created_at__lte=end_dt, paid_amount__gt=Decimal("0.00"))
            ) & ~Q(stage=Order.Stage.CANCELLED)
        ).select_related("responsible", "created_by", "payment_confirmed_by").order_by("-payment_confirmed_at", "-created_at")

        # Despesas na data selecionada
        expenses = Expense.objects.filter(
            status=Expense.Status.ACTIVE,
            expense_date=target_date
        ).select_related("created_by").order_by("-amount")

        # Agrupamento de recebimentos por método de pagamento
        methods_summary = {
            "pix": {"label": "PIX", "total": Decimal("0.00"), "count": 0, "icon": "fa-brands fa-pix", "color": "#22c55e"},
            "cartao_credito": {"label": "Cartão de Crédito", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-credit-card", "color": "#38bdf8"},
            "cartao_debito": {"label": "Cartão de Débito", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-id-card", "color": "#818cf8"},
            "cartao": {"label": "Cartão (Geral)", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-credit-card", "color": "#60a5fa"},
            "dinheiro": {"label": "Dinheiro (À Vista / Gaveta)", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-money-bill-wave", "color": "#34d399"},
            "transferencia": {"label": "Transferência / TED", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-building-columns", "color": "#fbbf24"},
            "saldo_credito": {"label": "Saldo do Plano / Crédito", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-wallet", "color": "#c084fc"},
            "outro": {"label": "Outros", "total": Decimal("0.00"), "count": 0, "icon": "fa-solid fa-circle-question", "color": "#9ca3af"},
        }

        total_revenue = Decimal("0.00")

        for o in orders:
            method = o.payment_method or "outro"
            if method not in methods_summary:
                method = "outro"
            paid = o.paid_amount or Decimal("0.00")
            methods_summary[method]["total"] += paid
            methods_summary[method]["count"] += 1
            total_revenue += paid

        # Agrupamento de despesas
        total_expenses = Decimal("0.00")
        for exp in expenses:
            total_expenses += exp.amount

        # Balanço da Gaveta Física (Dinheiro em Espécie)
        cash_in = methods_summary["dinheiro"]["total"]

        # Balanço Digital (PIX + Cartões + TED)
        digital_in = (
            methods_summary["pix"]["total"] +
            methods_summary["cartao_credito"]["total"] +
            methods_summary["cartao_debito"]["total"] +
            methods_summary["cartao"]["total"] +
            methods_summary["transferencia"]["total"]
        )

        # Saldo Geral
        net_balance = total_revenue - total_expenses

        if request.GET.get("export") == "csv":
            return self._csv_export(target_date, orders, expenses, methods_summary, total_revenue, total_expenses, cash_in, net_balance)

        prev_day = target_date - timedelta(days=1)
        next_day = target_date + timedelta(days=1)

        weekday_names = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
        weekday_label = weekday_names[target_date.weekday()]

        context = self.get_context_data(
            target_date=target_date,
            target_date_str=target_date.strftime("%Y-%m-%d"),
            target_date_display=target_date.strftime("%d/%m/%Y"),
            weekday_label=weekday_label,
            is_today=target_date == today,
            prev_day_str=prev_day.strftime("%Y-%m-%d"),
            next_day_str=next_day.strftime("%Y-%m-%d"),
            orders=orders,
            total_orders_count=len(orders),
            expenses=expenses,
            methods_summary=methods_summary,
            total_revenue=total_revenue,
            total_expenses=total_expenses,
            cash_in=cash_in,
            digital_in=digital_in,
            net_balance=net_balance,
        )
        return self.render_to_response(context)

    @staticmethod
    def _csv_export(target_date, orders, expenses, methods_summary, total_revenue, total_expenses, cash_in, net_balance):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="fechamento-caixa-{target_date:%Y%m%d}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")

        writer.writerow(["PRINT FORNECE - FECHAMENTO DE CAIXA DIÁRIO", target_date.strftime("%d/%m/%Y")])
        writer.writerow([])
        writer.writerow(["RESUMO POR FORMA DE PAGAMENTO"])
        writer.writerow(["Forma de Pagamento", "Qtd. Pedidos", "Total Recebido (R$)"])
        for k, v in methods_summary.items():
            if v["count"] > 0 or v["total"] > Decimal("0.00"):
                writer.writerow([v["label"], v["count"], f"{v['total']:.2f}".replace(".", ",")])
        writer.writerow(["TOTAL GERAL DE ENTRADAS", len(orders), f"{total_revenue:.2f}".replace(".", ",")])
        writer.writerow(["TOTAL DE DESPESAS / SAÍDAS", len(expenses), f"{total_expenses:.2f}".replace(".", ",")])
        writer.writerow(["TOTAL EM DINHEIRO / GAVETA", "", f"{cash_in:.2f}".replace(".", ",")])
        writer.writerow(["SALDO LÍQUIDO DO DIA", "", f"{net_balance:.2f}".replace(".", ",")])
        writer.writerow([])
        writer.writerow(["RECEBIMENTOS DO DIA"])
        writer.writerow(["Número", "Cliente", "Forma de Pagamento", "Valor Pago (R$)", "Situação", "Responsável", "Horário"])
        for o in orders:
            paid_dt = o.payment_confirmed_at or o.created_at
            time_str = timezone.localtime(paid_dt).strftime("%H:%M") if paid_dt else ""
            resp_name = o.responsible.name if o.responsible else (o.created_by.name if o.created_by else "")
            writer.writerow([
                o.number,
                o.client_name,
                o.get_payment_method_display(),
                f"{o.paid_amount:.2f}".replace(".", ","),
                o.get_payment_status_display(),
                resp_name,
                time_str
            ])
        writer.writerow([])
        writer.writerow(["DESPESAS / SAÍDAS DO DIA"])
        writer.writerow(["Descrição", "Categoria", "Observação", "Valor (R$)", "Responsável"])
        for exp in expenses:
            resp_name = exp.created_by.name if exp.created_by else ""
            writer.writerow([
                exp.description,
                exp.get_category_display() if hasattr(exp, "get_category_display") else exp.category,
                exp.note or "",
                f"{exp.amount:.2f}".replace(".", ","),
                resp_name
            ])
        return response
