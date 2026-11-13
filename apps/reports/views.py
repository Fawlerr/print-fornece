from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch, Q, Sum
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.models import SystemSetting, User
from apps.accounts.permissions import AdministratorRequiredMixin
from apps.expenses.models import Expense
from apps.inventory.models import SupplyItem, SupplyMovement
from apps.orders.models import Order, OrderItem, OrderPayment, OrderStageHistory
from apps.payments.models import Cliente

from .exports import ExportSection
from .forms import ProductionReportFilterForm, ReportFilterForm
from .mixins import PeriodReportMixin, SummaryMetric

WEEKDAYS_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
WEEKDAYS_LONG = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
MONTH_NAMES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def item_meters(item) -> Decimal:
    """Metros de filme usados por um item (mesma regra usada em todo o sistema)."""
    if item.calculation_snapshot and "film_used_m" in item.calculation_snapshot:
        return Decimal(str(item.calculation_snapshot["film_used_m"]))
    if "metro" in (item.billing_unit or "").lower():
        return Decimal(str(item.billing_quantity))
    if item.used_length_cm:
        return Decimal(str(item.used_length_cm)) / Decimal("100")
    return Decimal("0.00")


def orders_created_in(period, **filters):
    """Pedidos criados no período (início inclusivo, fim exclusivo = dia final inteiro)."""
    return Order.objects.filter(created_at__gte=period.start_at, created_at__lt=period.end_at, **filters)


def iter_days(period):
    current = period.start
    while current <= period.end:
        yield current
        current += timedelta(days=1)


class ReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/index.html"
    report_title = "Visão geral e financeiro"
    report_slug = "relatorio-geral"
    preserved_params = ("stage", "payment_status", "responsible", "priority")

    def _filters(self):
        form = ReportFilterForm(self.request.GET or None)
        data = form.cleaned_data if form.is_bound and form.is_valid() else {}
        return form, data

    def _orders(self, data, period):
        queryset = orders_created_in(period).select_related("responsible").prefetch_related(
            Prefetch("stage_history", queryset=OrderStageHistory.objects.order_by("created_at", "pk"))
        ).order_by("-created_at", "-pk")
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
        active_stages = (Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT, Order.Stage.PAYMENT_CONFIRMED, Order.Stage.PRE_PRESS, Order.Stage.PRODUCTION, Order.Stage.READY)
        for order in orders:
            history = list(order.stage_history.all())
            for index, item in enumerate(history):
                next_at = history[index + 1].created_at if index + 1 < len(history) else now
                if item.new_stage in active_stages and next_at >= item.created_at:
                    totals[item.new_stage] += Decimal(str((next_at - item.created_at).total_seconds() / 3600))
                    counts[item.new_stage] += 1
        return {stage: (round(totals[stage] / counts[stage], 1) if counts[stage] else None) for stage in active_stages}

    def build(self, period):
        form, data = self._filters()
        orders = list(self._orders(data, period))
        active = [order for order in orders if order.stage != Order.Stage.CANCELLED]
        paid = sum((order.paid_amount for order in active), Decimal("0"))
        pending = sum((max(Decimal("0"), order.total_amount - order.paid_amount) for order in active), Decimal("0"))
        completed = sum(order.stage in (Order.Stage.DELIVERED, "finalizado") for order in orders)
        cancelled = sum(order.stage == Order.Stage.CANCELLED for order in orders)
        ticket = sum((order.total_amount for order in active), Decimal("0")) / len(active) if active else Decimal("0")
        shirt_discount = OrderItem.objects.filter(order__in=[o.pk for o in active]).aggregate(total=Sum("discount_total"))["total"] or Decimal("0")
        expenses = Expense.objects.filter(status=Expense.Status.ACTIVE, expense_date__range=(period.start, period.end)).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return {
            "filter_form": form,
            "orders": orders,
            "users": User.objects.filter(is_active=True).only("id", "name").order_by("name"),
            "paid": paid,
            "pending": pending,
            "expenses": expenses,
            "profit": paid - expenses,
            "ticket": ticket,
            "shirt_discount": shirt_discount,
            "completed": completed,
            "cancelled": cancelled,
            "stage_durations": self._stage_durations(orders),
            "order_count": len(orders),
            "summary": [
                SummaryMetric("Pedidos", len(orders), "number"),
                SummaryMetric("Faturamento pago", paid),
                SummaryMetric("A receber", pending),
                SummaryMetric("Despesas", expenses),
                SummaryMetric("Lucro líquido", paid - expenses),
                SummaryMetric("Ticket médio", ticket),
            ],
            "export_sections": [ExportSection(
                headers=["Número", "Cliente", "WhatsApp", "Valor total", "Valor pago", "Pagamento", "Etapa", "Prioridade", "Responsável", "Criado em"],
                rows=[[
                    o.number, o.client_name, o.client_whatsapp, o.total_amount, o.paid_amount, o.get_payment_status_display(),
                    o.get_stage_display(), o.get_priority_display(), o.responsible.name if o.responsible_id else "", o.created_at,
                ] for o in orders],
            )],
        }


class ProductionReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/production.html"
    report_title = "Produção diária (metros)"
    report_slug = "relatorio-producao-metros"
    preserved_params = ("responsible", "material_type")

    def build(self, period):
        responsible_id = self.request.GET.get("responsible")
        material_type = self.request.GET.get("material_type") or ""
        form = ProductionReportFilterForm(initial={"responsible": responsible_id, "material_type": material_type}, data=self.request.GET or None)

        orders_qs = orders_created_in(period).exclude(stage=Order.Stage.CANCELLED).select_related("responsible", "created_by").prefetch_related("items")
        if responsible_id:
            try:
                resp_pk = int(responsible_id)
                orders_qs = orders_qs.filter(Q(responsible_id=resp_pk) | Q(created_by_id=resp_pk))
            except (ValueError, TypeError):
                pass

        days_map: dict[date, dict] = {
            day: {
                "date": day, "day_num": day.day, "weekday": WEEKDAYS_SHORT[day.weekday()],
                "textil_meters": Decimal("0.00"), "uv_meters": Decimal("0.00"), "total_meters": Decimal("0.00"),
                "orders_count": 0, "orders_list": [],
            }
            for day in iter_days(period)
        }
        total_orders_set = set()
        for order in orders_qs.order_by("created_at", "pk"):
            order_date = timezone.localtime(order.created_at).date()
            if order_date not in days_map:
                continue
            order_has_dtf = False
            for item in order.items.all():
                mat_code = (item.material_code or "").lower()
                mat_name = (item.material_name or "").lower()
                is_uv = "uv" in mat_code or "uv" in mat_name
                is_textil = mat_code == "dtf_textil" or (getattr(item, "kind", "") == "material" and not is_uv)
                if material_type == "dtf_textil" and not is_textil:
                    continue
                if material_type == "dtf_uv" and not is_uv:
                    continue
                meters = item_meters(item)
                if meters > 0:
                    order_has_dtf = True
                    days_map[order_date]["uv_meters" if is_uv else "textil_meters"] += meters
                    days_map[order_date]["total_meters"] += meters
            if order_has_dtf:
                days_map[order_date]["orders_count"] += 1
                days_map[order_date]["orders_list"].append(order)
                total_orders_set.add(order.id)

        daily_rows = list(days_map.values())
        total_textil = sum((r["textil_meters"] for r in daily_rows), Decimal("0.00"))
        total_uv = sum((r["uv_meters"] for r in daily_rows), Decimal("0.00"))
        total_meters = total_textil + total_uv
        active_days = sum(1 for r in daily_rows if r["total_meters"] > 0)
        avg_daily = (total_meters / Decimal(active_days)) if active_days else Decimal("0.00")
        peak_row = max(daily_rows, key=lambda r: r["total_meters"], default=None)
        peak_meters = peak_row["total_meters"] if peak_row else Decimal("0.00")
        peak_date = peak_row["date"] if peak_row and peak_meters > 0 else None
        return {
            "form": form,
            "users": User.objects.filter(is_active=True).only("id", "name").order_by("name"),
            "daily_rows": daily_rows,
            "total_textil": total_textil,
            "total_uv": total_uv,
            "total_meters": total_meters,
            "active_days": active_days,
            "avg_daily": avg_daily,
            "peak_meters": peak_meters,
            "peak_date": peak_date,
            "total_orders_count": len(total_orders_set),
            "responsible_id": responsible_id,
            "material_type": material_type,
            "summary": [
                SummaryMetric("DTF Têxtil (m)", total_textil, "meters"),
                SummaryMetric("DTF UV (m)", total_uv, "meters"),
                SummaryMetric("Total de metros", total_meters, "meters"),
                SummaryMetric("Pedidos com DTF", len(total_orders_set), "number"),
            ],
            "export_sections": [ExportSection(
                headers=["Data", "Dia da Semana", "DTF Têxtil (m)", "DTF UV (m)", "Total de Metros (m)", "Qtd. Pedidos", "Números dos Pedidos"],
                rows=[[r["date"], r["weekday"], r["textil_meters"], r["uv_meters"], r["total_meters"], r["orders_count"], ", ".join(o.number for o in r["orders_list"])] for r in daily_rows],
                totals=["TOTAL", "", total_textil, total_uv, total_meters, len(total_orders_set), ""],
            )],
        }


CASH_METHODS = {
    "pix": ("PIX", "fa-brands fa-pix", "#22c55e"),
    "cartao_credito": ("Cartão de Crédito", "fa-solid fa-credit-card", "#38bdf8"),
    "cartao_debito": ("Cartão de Débito", "fa-solid fa-id-card", "#818cf8"),
    "cartao": ("Cartão (Geral)", "fa-solid fa-credit-card", "#60a5fa"),
    "dinheiro": ("Dinheiro (À Vista / Gaveta)", "fa-solid fa-money-bill-wave", "#34d399"),
    "transferencia": ("Transferência / TED", "fa-solid fa-building-columns", "#fbbf24"),
    "saldo_credito": ("Saldo do Plano / Crédito", "fa-solid fa-wallet", "#c084fc"),
    "outro": ("Outros", "fa-solid fa-circle-question", "#9ca3af"),
}


class CashRegisterReportView(LoginRequiredMixin, PeriodReportMixin, TemplateView):
    """Fechamento de caixa: padrão "hoje"; um período pode ser escolhido só para consulta."""

    template_name = "reports/cash_register.html"
    report_title = "Fechamento de caixa"
    report_slug = "fechamento-caixa"
    period_basis = "data de confirmação do pagamento (ou de criação, se o pagamento não tiver confirmação registrada)"
    period_default = "hoje"
    period_use_session = False
    preserved_params = ("payment_type",)

    def pre_check(self, request):
        is_unlocked = SystemSetting.is_feature_enabled("cash_register", default=False)
        if not is_unlocked and not getattr(request.user, "is_dev", False):
            return self.response_class(request=request, template="reports/cash_locked.html", context={}, using=self.template_engine)
        return None

    def build(self, period):
        today = timezone.localdate()
        orders = Order.objects.filter(
            (
                Q(payment_confirmed_at__gte=period.start_at, payment_confirmed_at__lt=period.end_at)
                | Q(payment_confirmed_at__isnull=True, created_at__gte=period.start_at, created_at__lt=period.end_at, paid_amount__gt=Decimal("0.00"))
            ) & ~Q(stage=Order.Stage.CANCELLED)
        ).select_related("responsible", "created_by", "payment_confirmed_by").prefetch_related("payments").order_by("-payment_confirmed_at", "-created_at")
        expenses = Expense.objects.filter(status=Expense.Status.ACTIVE, expense_date__range=(period.start, period.end)).select_related("created_by").order_by("-amount")

        all_orders = list(orders)
        complete_orders = [o for o in all_orders if o.payment_status == Order.PaymentStatus.PAID]
        partial_orders = [o for o in all_orders if o.payment_status == Order.PaymentStatus.PARTIAL]
        payment_type = self.request.GET.get("payment_type", "todos").strip()
        if payment_type == "completo":
            display_orders = complete_orders
        elif payment_type == "parcial":
            display_orders = partial_orders
        else:
            payment_type = "todos"
            display_orders = all_orders

        methods_summary = {key: {"label": label, "total": Decimal("0.00"), "count": 0, "icon": icon, "color": color} for key, (label, icon, color) in CASH_METHODS.items()}
        total_revenue = Decimal("0.00")
        for o in display_orders:
            splits = list(o.payments.all())
            entries = [(sp.payment_method, sp.amount) for sp in splits] if splits else [(o.payment_method, o.paid_amount or Decimal("0.00"))]
            for method, amount in entries:
                method = method if method in methods_summary else "outro"
                methods_summary[method]["total"] += amount
                methods_summary[method]["count"] += 1
                total_revenue += amount

        total_expenses = sum((exp.amount for exp in expenses), Decimal("0.00"))
        cash_in = methods_summary["dinheiro"]["total"]
        digital_in = sum((methods_summary[k]["total"] for k in ("pix", "cartao_credito", "cartao_debito", "cartao", "transferencia")), Decimal("0.00"))
        net_balance = total_revenue - total_expenses
        single_day = period.start == period.end
        target_date = period.end

        def responsible_name(order):
            return order.responsible.name if order.responsible else (order.created_by.name if order.created_by else "")

        return {
            "target_date": target_date,
            "target_date_str": target_date.strftime("%Y-%m-%d"),
            "target_date_display": period.label,
            "weekday_label": WEEKDAYS_LONG[target_date.weekday()] if single_day else f"{period.days} dias",
            "is_single_day": single_day,
            "is_today": single_day and target_date == today,
            "orders": display_orders,
            "total_orders_count": len(display_orders),
            "all_orders_count": len(all_orders),
            "payment_type": payment_type,
            "complete_count": len(complete_orders),
            "complete_total": sum((o.paid_amount for o in complete_orders), Decimal("0.00")),
            "partial_count": len(partial_orders),
            "partial_total": sum((o.paid_amount for o in partial_orders), Decimal("0.00")),
            "expenses": expenses,
            "methods_summary": methods_summary,
            "total_revenue": total_revenue,
            "total_expenses": total_expenses,
            "cash_in": cash_in,
            "cash_drawer_net": cash_in,
            "digital_in": digital_in,
            "net_balance": net_balance,
            "summary": [
                SummaryMetric("Total recebido", total_revenue),
                SummaryMetric("Despesas / saídas", total_expenses),
                SummaryMetric("Dinheiro na gaveta", cash_in),
                SummaryMetric("Saldo líquido", net_balance),
            ],
            "export_sections": [
                ExportSection(
                    title="Resumo por forma de pagamento",
                    headers=["Forma de Pagamento", "Qtd. Pedidos", "Total Recebido (R$)"],
                    rows=[[v["label"], v["count"], v["total"]] for v in methods_summary.values() if v["count"] or v["total"]],
                    totals=["TOTAL GERAL DE ENTRADAS", len(display_orders), total_revenue],
                ),
                ExportSection(
                    title="Totais",
                    headers=["Indicador", "Valor (R$)"],
                    rows=[["Total de despesas / saídas", total_expenses], ["Total em dinheiro / gaveta", cash_in], ["Saldo líquido", net_balance]],
                ),
                ExportSection(
                    title="Recebimentos",
                    headers=["Número", "Cliente", "Forma de Pagamento", "Valor Pago (R$)", "Situação", "Responsável", "Data/Hora"],
                    rows=[[o.number, o.client_name, o.get_payment_method_display(), o.paid_amount, o.get_payment_status_display(), responsible_name(o), o.payment_confirmed_at or o.created_at] for o in display_orders],
                ),
                ExportSection(
                    title="Despesas / saídas",
                    headers=["Data", "Descrição", "Categoria", "Observação", "Valor (R$)", "Responsável"],
                    rows=[[e.expense_date, e.description, e.get_category_display() if hasattr(e, "get_category_display") else e.category, e.note or "", e.amount, e.created_by.name if e.created_by else ""] for e in expenses],
                ),
            ],
        }


class CashRegisterBetaView(LoginRequiredMixin, TemplateView):
    template_name = "reports/cash_register_beta.html"

    def _get_session_data(self):
        default_data = {
            "status": "fechado",  # 'fechado', 'aberto', 'encerrado'
            "abertura": None,
            "movimentacoes": [],
            "fechamento": None,
        }
        return self.request.session.get("caixa_beta", default_data)

    def _save_session_data(self, data):
        self.request.session["caixa_beta"] = data
        self.request.session.modified = True

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "").strip()
        data = self._get_session_data()
        now_str = timezone.localtime().strftime("%d/%m/%Y às %H:%M")
        user_name = request.user.name or request.user.email

        if action == "abrir":
            raw_val = request.POST.get("fundo_inicial", "100,00").replace(".", "").replace(",", ".").strip()
            try:
                fundo = max(float(raw_val), 0.0)
            except ValueError:
                fundo = 100.00
            data["status"] = "aberto"
            data["abertura"] = {
                "fundo_inicial": fundo,
                "horario": now_str,
                "operador": user_name,
            }
            data["movimentacoes"] = []
            data["fechamento"] = None
            self._save_session_data(data)
            messages.success(request, f"Caixa aberto com sucesso com fundo de troco de R$ {fundo:.2f}!")

        elif action == "sangria":
            raw_val = request.POST.get("valor", "").replace(".", "").replace(",", ".").strip()
            motivo = request.POST.get("motivo", "Retirada de caixa (Sangria)").strip()
            categoria = request.POST.get("categoria", "geral").strip()
            try:
                val = max(float(raw_val), 0.0)
                if val > 0:
                    data["movimentacoes"].append({
                        "tipo": "sangria",
                        "valor": val,
                        "motivo": motivo,
                        "categoria": categoria,
                        "horario": timezone.localtime().strftime("%H:%M"),
                        "operador": user_name,
                    })
                    self._save_session_data(data)
                    messages.success(request, f"Sangria de R$ {val:.2f} registrada com sucesso!")
            except ValueError:
                messages.error(request, "Valor inválido para sangria.")

        elif action == "suprimento":
            raw_val = request.POST.get("valor", "").replace(".", "").replace(",", ".").strip()
            motivo = request.POST.get("motivo", "Reforço de troco (Suprimento)").strip()
            categoria = request.POST.get("categoria", "geral").strip()
            try:
                val = max(float(raw_val), 0.0)
                if val > 0:
                    data["movimentacoes"].append({
                        "tipo": "suprimento",
                        "valor": val,
                        "motivo": motivo,
                        "categoria": categoria,
                        "horario": timezone.localtime().strftime("%H:%M"),
                        "operador": user_name,
                    })
                    self._save_session_data(data)
                    messages.success(request, f"Suprimento de R$ {val:.2f} adicionado à gaveta!")
            except ValueError:
                messages.error(request, "Valor inválido para suprimento.")

        elif action == "fechar":
            raw_val = request.POST.get("dinheiro_informado", "0").replace(".", "").replace(",", ".").strip()
            try:
                informado = float(raw_val)
            except ValueError:
                informado = 0.0

            # Calcular esperado
            today = timezone.localdate()
            start_dt = timezone.make_aware(datetime.combine(today, time.min))
            end_dt = timezone.make_aware(datetime.combine(today, time.max))
            orders_today = Order.objects.filter(
                (
                    Q(payment_confirmed_at__gte=start_dt, payment_confirmed_at__lte=end_dt) |
                    Q(payment_confirmed_at__isnull=True, created_at__gte=start_dt, created_at__lte=end_dt, paid_amount__gt=Decimal("0.00"))
                ) & ~Q(stage=Order.Stage.CANCELLED)
            )
            dinheiro_vendas = sum(float(o.paid_amount) for o in orders_today if o.payment_method == Order.PaymentMethod.CASH)
            fundo = data.get("abertura", {}).get("fundo_inicial", 0.0)
            total_sangrias = sum(m["valor"] for m in data.get("movimentacoes", []) if m["tipo"] == "sangria")
            total_suprimentos = sum(m["valor"] for m in data.get("movimentacoes", []) if m["tipo"] == "suprimento")
            esperado = fundo + dinheiro_vendas + total_suprimentos - total_sangrias
            dif = informado - esperado

            status_dif = "exato"
            if dif > 0.01:
                status_dif = "sobra"
            elif dif < -0.01:
                status_dif = "falta"

            data["status"] = "encerrado"
            data["fechamento"] = {
                "horario": now_str,
                "operador": user_name,
                "dinheiro_informado": informado,
                "dinheiro_esperado": esperado,
                "diferenca": dif,
                "status_diferenca": status_dif,
            }
            self._save_session_data(data)
            messages.success(request, "Fechamento de caixa concluído com sucesso!")

        elif action in ("reset", "reabrir"):
            self.request.session["caixa_beta"] = {
                "status": "fechado",
                "abertura": None,
                "movimentacoes": [],
                "fechamento": None,
            }
            self.request.session.modified = True
            messages.info(request, "Demonstração do caixa reiniciada. Pronto para uma nova abertura!")

        return redirect("reports:cash_register_beta")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session_data = self._get_session_data()
        today = timezone.localdate()
        start_dt = timezone.make_aware(datetime.combine(today, time.min))
        end_dt = timezone.make_aware(datetime.combine(today, time.max))

        orders = Order.objects.filter(
            (
                Q(payment_confirmed_at__gte=start_dt, payment_confirmed_at__lte=end_dt) |
                Q(payment_confirmed_at__isnull=True, created_at__gte=start_dt, created_at__lte=end_dt, paid_amount__gt=Decimal("0.00"))
            ) & ~Q(stage=Order.Stage.CANCELLED)
        ).select_related("responsible", "created_by").order_by("-payment_confirmed_at", "-created_at")

        # Totais de vendas reais do dia
        vendas = {
            "pix": Decimal("0.00"),
            "cartao_credito": Decimal("0.00"),
            "cartao_debito": Decimal("0.00"),
            "dinheiro": Decimal("0.00"),
            "outros": Decimal("0.00"),
            "total": Decimal("0.00"),
            "qtd_pedidos": len(orders),
        }
        for o in orders:
            paid = o.paid_amount or Decimal("0.00")
            vendas["total"] += paid
            if o.payment_method == Order.PaymentMethod.PIX:
                vendas["pix"] += paid
            elif o.payment_method == Order.PaymentMethod.CREDIT_CARD:
                vendas["cartao_credito"] += paid
            elif o.payment_method == Order.PaymentMethod.DEBIT_CARD:
                vendas["cartao_debito"] += paid
            elif o.payment_method == Order.PaymentMethod.CASH:
                vendas["dinheiro"] += paid
            else:
                vendas["outros"] += paid

        # Totais de movimentações do caixa na sessão
        fundo_inicial = float(session_data.get("abertura", {}).get("fundo_inicial", 0.0) if session_data.get("abertura") else 0.0)
        movimentacoes = session_data.get("movimentacoes", [])
        total_sangrias = sum(m["valor"] for m in movimentacoes if m["tipo"] == "sangria")
        total_suprimentos = sum(m["valor"] for m in movimentacoes if m["tipo"] == "suprimento")
        dinheiro_vendas_float = float(vendas["dinheiro"])
        saldo_gaveta_esperado = fundo_inicial + dinheiro_vendas_float + total_suprimentos - total_sangrias

        # Percentuais de meios de pagamento
        vendas_total_float = float(vendas["total"])
        if vendas_total_float > 0:
            pct_pix = round((float(vendas["pix"]) / vendas_total_float) * 100, 1)
            pct_credito = round((float(vendas["cartao_credito"]) / vendas_total_float) * 100, 1)
            pct_debito = round((float(vendas["cartao_debito"]) / vendas_total_float) * 100, 1)
            pct_dinheiro = round((float(vendas["dinheiro"]) / vendas_total_float) * 100, 1)
            pct_outros = max(round(100.0 - (pct_pix + pct_credito + pct_debito + pct_dinheiro), 1), 0.0)
        else:
            pct_pix = pct_credito = pct_debito = pct_dinheiro = pct_outros = 0.0

        # Linha do tempo visual cronológica do turno
        timeline = []
        abertura = session_data.get("abertura")
        if abertura:
            timeline.append({
                "horario": abertura.get("horario", "").split("às")[-1].strip() if "às" in abertura.get("horario", "") else "Início",
                "tipo": "abertura",
                "titulo": "Abertura de Caixa (Fundo de Troco)",
                "detalhe": f"Operador: {abertura.get('operador', '-')}",
                "icone": "fa-solid fa-lock-open",
                "cor": "#38bdf8",
                "valor_str": f"+R$ {fundo_inicial:.2f}",
                "impacto": "positivo",
            })

        for o in orders:
            if o.payment_method == Order.PaymentMethod.CASH and (o.paid_amount or Decimal("0.00")) > Decimal("0.00"):
                paid_dt = o.payment_confirmed_at or o.created_at
                h_str = timezone.localtime(paid_dt).strftime("%H:%M") if paid_dt else "--:--"
                timeline.append({
                    "horario": h_str,
                    "tipo": "venda_dinheiro",
                    "titulo": f"Venda em Dinheiro #{o.number}",
                    "detalhe": f"Cliente: {o.client_name}",
                    "icone": "fa-solid fa-money-bill-wave",
                    "cor": "#22c55e",
                    "valor_str": f"+R$ {o.paid_amount:.2f}",
                    "impacto": "positivo",
                })

        for m in movimentacoes:
            if m["tipo"] == "sangria":
                timeline.append({
                    "horario": m.get("horario", "--:--"),
                    "tipo": "sangria",
                    "titulo": f"Sangria: {m.get('motivo')}",
                    "detalhe": f"Retirado por: {m.get('operador')}",
                    "icone": "fa-solid fa-arrow-up",
                    "cor": "#ef4444",
                    "valor_str": f"-R$ {m.get('valor', 0):.2f}",
                    "impacto": "negativo",
                })
            else:
                timeline.append({
                    "horario": m.get("horario", "--:--"),
                    "tipo": "suprimento",
                    "titulo": f"Suprimento: {m.get('motivo')}",
                    "detalhe": f"Inserido por: {m.get('operador')}",
                    "icone": "fa-solid fa-arrow-down",
                    "cor": "#38bdf8",
                    "valor_str": f"+R$ {m.get('valor', 0):.2f}",
                    "impacto": "positivo",
                })

        fechamento = session_data.get("fechamento")
        if fechamento:
            timeline.append({
                "horario": fechamento.get("horario", "").split("às")[-1].strip() if "às" in fechamento.get("horario", "") else "Fim",
                "tipo": "fechamento",
                "titulo": "Fechamento de Caixa Realizado",
                "detalhe": f"Conferência: {fechamento.get('status_diferenca', '').upper()} (Contado: R$ {fechamento.get('dinheiro_informado', 0):.2f})",
                "icone": "fa-solid fa-lock",
                "cor": "#e11d48",
                "valor_str": f"Esperado: R$ {fechamento.get('dinheiro_esperado', 0):.2f}",
                "impacto": "neutro",
            })

        context.update({
            "session_caixa": session_data,
            "status_caixa": session_data.get("status", "fechado"),
            "abertura": session_data.get("abertura"),
            "movimentacoes": movimentacoes,
            "fechamento": session_data.get("fechamento"),
            "fundo_inicial": fundo_inicial,
            "total_sangrias": total_sangrias,
            "total_suprimentos": total_suprimentos,
            "saldo_gaveta_esperado": saldo_gaveta_esperado,
            "alerta_limite_gaveta": saldo_gaveta_esperado >= 500.0,
            "vendas": vendas,
            "pct_pix": pct_pix,
            "pct_credito": pct_credito,
            "pct_debito": pct_debito,
            "pct_dinheiro": pct_dinheiro,
            "pct_outros": pct_outros,
            "timeline": timeline,
            "orders": orders,
            "today_display": today.strftime("%d/%m/%Y"),
            "is_beta": True,
        })
        return context


def _material_bucket(item) -> str:
    mat_code = (item.material_code or "").lower()
    mat_name = (item.material_name or "").lower()
    kind = getattr(item, "kind", "")
    if "uv" in mat_code or "uv" in mat_name:
        return "dtf_uv"
    if mat_code == "dtf_textil" or (kind == "material" and "uv" not in mat_code):
        return "dtf_textil"
    if kind == "produto" or "camisa" in mat_code or "camisa" in mat_name:
        return "camisas"
    if kind in {"servico", "ajuste"} or "ajuste" in mat_code or "vetorizacao" in mat_code:
        return "servicos"
    return "outros"


MATERIAL_ROWS = [
    ("dtf_textil", "DTF Têxtil (Metro)", "DTF", "fa-solid fa-print", "#38bdf8"),
    ("dtf_uv", "DTF UV (Metro / Rolo)", "DTF UV", "fa-solid fa-sun", "#c084fc"),
    ("camisas", "Camisetas / Vestuário", "Produtos", "fa-solid fa-shirt", "#34d399"),
    ("servicos", "Serviços Gráficos / Ajustes", "Serviços", "fa-solid fa-wand-magic-sparkles", "#fbbf24"),
    ("outros", "Outros Materiais", "Diversos", "fa-solid fa-boxes-stacked", "#94a3b8"),
]


class MaterialReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/materials.html"
    report_title = "Consumo de materiais"
    report_slug = "relatorio-materiais"
    period_basis = "data de criação do pedido (somente pedidos prontos ou entregues)"

    def build(self, period):
        orders = orders_created_in(period, stage__in=[Order.Stage.READY, Order.Stage.DELIVERED]).prefetch_related("items")
        materials_map = {
            code: {"code": code, "name": name, "category": category, "meters": Decimal("0.00"), "items_count": 0, "orders_count": 0,
                   "total_revenue": Decimal("0.00"), "orders_set": set(), "icon": icon, "color": color}
            for code, name, category, icon, color in MATERIAL_ROWS
        }
        orders = list(orders)
        for order in orders:
            for item in order.items.all():
                bucket = materials_map[_material_bucket(item)]
                bucket["meters"] += item_meters(item)
                bucket["items_count"] += int(item.art_quantity or item.billing_quantity or 1)
                bucket["total_revenue"] += item.line_total
                bucket["orders_set"].add(order.id)

        material_rows = list(materials_map.values())
        for row in material_rows:
            row["orders_count"] = len(row["orders_set"])
        grand_total_meters = sum((r["meters"] for r in material_rows), Decimal("0.00"))
        grand_total_revenue = sum((r["total_revenue"] for r in material_rows), Decimal("0.00"))
        material_rows.sort(key=lambda x: (x["meters"], x["total_revenue"]), reverse=True)
        for r in material_rows:
            r["percentage"] = (float(r["meters"] / grand_total_meters) * 100) if grand_total_meters > 0 else 0.0
        return {
            "material_rows": material_rows,
            "grand_total_meters": grand_total_meters,
            "grand_total_revenue": grand_total_revenue,
            "total_orders_count": len(orders),
            "summary": [
                SummaryMetric("Total de metros", grand_total_meters, "meters"),
                SummaryMetric("Faturamento", grand_total_revenue),
                SummaryMetric("Pedidos", len(orders), "number"),
            ],
            "export_sections": [ExportSection(
                headers=["Material / Categoria", "Total Metros (m)", "Qtd. Itens/Peças", "Qtd. Pedidos", "Faturamento Total (R$)", "Participação (%)"],
                rows=[[r["name"], r["meters"], r["items_count"], r["orders_count"], r["total_revenue"], f"{r['percentage']:.1f}%".replace(".", ",")] for r in material_rows],
                totals=["TOTAL GERAL", grand_total_meters, "", "", grand_total_revenue, "100%"],
            )],
        }


class TeamRankingReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/team_ranking.html"
    report_title = "Ranking de vendas da equipe"
    report_slug = "ranking-equipe"

    def build(self, period):
        orders = orders_created_in(period).exclude(stage=Order.Stage.CANCELLED).select_related("responsible", "created_by").prefetch_related("items")
        users_map: dict[int, dict] = {}
        for order in orders:
            user = order.responsible or order.created_by
            if not user:
                continue
            row = users_map.setdefault(user.pk, {
                "user": user, "user_id": user.pk, "name": user.name or user.email,
                "role_display": getattr(user, "get_role_display", lambda: user.role)(),
                "total_sales": Decimal("0.00"), "total_paid": Decimal("0.00"), "orders_count": 0,
                "completed_orders": 0, "total_meters": Decimal("0.00"),
            })
            row["total_sales"] += order.total_amount
            row["total_paid"] += order.paid_amount or Decimal("0.00")
            row["orders_count"] += 1
            if order.stage in {Order.Stage.READY, Order.Stage.DELIVERED}:
                row["completed_orders"] += 1
                row["total_meters"] += order.total_meters

        team_rows = sorted(users_map.values(), key=lambda x: x["total_sales"], reverse=True)
        grand_sales = sum((r["total_sales"] for r in team_rows), Decimal("0.00"))
        grand_orders = sum(r["orders_count"] for r in team_rows)
        for idx, r in enumerate(team_rows, start=1):
            r["rank"] = idx
            r["avg_ticket"] = (r["total_sales"] / Decimal(r["orders_count"])) if r["orders_count"] else Decimal("0.00")
            r["share_percentage"] = (float(r["total_sales"] / grand_sales) * 100) if grand_sales > 0 else 0.0
        return {
            "team_rows": team_rows,
            "grand_sales": grand_sales,
            "grand_orders": grand_orders,
            "summary": [
                SummaryMetric("Volume de vendas", grand_sales),
                SummaryMetric("Pedidos", grand_orders, "number"),
            ],
            "export_sections": [ExportSection(
                headers=["Posição", "Atendente / Vendedor", "Volume de Vendas (R$)", "Qtd. Pedidos", "Ticket Médio (R$)", "Metros Produzidos (m)", "Participação (%)"],
                rows=[[f"{r['rank']}º", r["name"], r["total_sales"], r["orders_count"], r["avg_ticket"], r["total_meters"], f"{r['share_percentage']:.1f}%".replace(".", ",")] for r in team_rows],
                totals=["TOTAL GERAL", "", grand_sales, grand_orders, "", "", "100%"],
            )],
        }


class CustomerRankingReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/customers_ranking.html"
    report_title = "Ranking de clientes"
    report_slug = "ranking-clientes"
    preserved_params = ("order_by",)

    def build(self, period):
        order_by = self.request.GET.get("order_by", "volume").strip().lower()
        if order_by not in {"volume", "quantidade"}:
            order_by = "volume"
        orders = orders_created_in(period).exclude(stage=Order.Stage.CANCELLED).select_related("cliente").prefetch_related("items")
        customers_map: dict[str, dict] = {}
        for order in orders:
            if order.cliente_id:
                key, client_name = f"id_{order.cliente_id}", order.cliente.nome
                client_phone = order.cliente.telefone or order.client_whatsapp
            else:
                key, client_name, client_phone = f"raw_{order.client_name.strip().lower()}", order.client_name, order.client_whatsapp
            row = customers_map.setdefault(key, {
                "cliente_obj": order.cliente, "name": client_name, "phone": client_phone,
                "total_sales": Decimal("0.00"), "total_paid": Decimal("0.00"), "orders_count": 0,
                "total_items_qty": 0, "total_meters": Decimal("0.00"), "last_order_date": order.created_at,
            })
            row["total_sales"] += order.total_amount
            row["total_paid"] += order.paid_amount or Decimal("0.00")
            row["orders_count"] += 1
            row["last_order_date"] = max(row["last_order_date"], order.created_at)
            for item in order.items.all():
                row["total_items_qty"] += int(item.art_quantity or item.billing_quantity or 1)
                if getattr(item, "kind", "") == "material" or "metro" in (item.billing_unit or "").lower():
                    if item.calculation_snapshot and "film_used_m" in item.calculation_snapshot:
                        row["total_meters"] += Decimal(str(item.calculation_snapshot["film_used_m"]))
                    elif item.billing_quantity:
                        row["total_meters"] += Decimal(str(item.billing_quantity))

        customer_rows = list(customers_map.values())
        if order_by == "quantidade":
            customer_rows.sort(key=lambda x: (x["total_items_qty"], x["total_meters"], x["total_sales"]), reverse=True)
        else:
            customer_rows.sort(key=lambda x: (x["total_sales"], x["total_items_qty"]), reverse=True)
        grand_revenue = sum((r["total_sales"] for r in customer_rows), Decimal("0.00"))
        grand_orders = sum(r["orders_count"] for r in customer_rows)
        for idx, r in enumerate(customer_rows, start=1):
            r["rank"] = idx
            r["avg_ticket"] = (r["total_sales"] / Decimal(r["orders_count"])) if r["orders_count"] else Decimal("0.00")
        return {
            "order_by": order_by,
            "customer_rows": customer_rows[:100],
            "total_customers_count": len(customer_rows),
            "grand_revenue": grand_revenue,
            "grand_orders": grand_orders,
            "summary": [
                SummaryMetric("Faturamento", grand_revenue),
                SummaryMetric("Pedidos", grand_orders, "number"),
                SummaryMetric("Clientes", len(customer_rows), "number"),
            ],
            "export_sections": [ExportSection(
                title=f"Ordenação por: {'Volume Financeiro (R$)' if order_by == 'volume' else 'Quantidade Comprada'}",
                headers=["Posição", "Cliente", "WhatsApp / Telefone", "Volume Total Gasto (R$)", "Qtd. Itens/Produtos", "Metros DTF (m)", "Total Pedidos", "Ticket Médio (R$)", "Última Compra"],
                rows=[[f"{r['rank']}º", r["name"], r["phone"] or "", r["total_sales"], r["total_items_qty"], r["total_meters"], r["orders_count"], r["avg_ticket"], r["last_order_date"]] for r in customer_rows],
                totals=["TOTAL GERAL", "", "", grand_revenue, "", "", grand_orders, "", ""],
            )],
        }


PRODUCT_CATEGORIES = {
    "DTF UV": "#c084fc",
    "DTF Têxtil": "#38bdf8",
    "Camisetas": "#34d399",
    "Serviços / Ajustes": "#fbbf24",
    "Diversos": "#94a3b8",
}


def _product_category(item) -> str:
    name = (item.material_name or "").lower()
    mat_code = (item.material_code or "").lower()
    kind = getattr(item, "kind", "")
    if "uv" in mat_code or "uv" in name:
        return "DTF UV"
    if mat_code == "dtf_textil" or kind == OrderItem.Kind.MATERIAL:
        return "DTF Têxtil"
    if kind == OrderItem.Kind.PRODUCT or "camisa" in mat_code or "camisa" in name:
        return "Camisetas"
    if kind in {OrderItem.Kind.SERVICE, OrderItem.Kind.ADJUSTMENT} or "servico" in mat_code or "ajuste" in mat_code:
        return "Serviços / Ajustes"
    return "Diversos"


class ProductSalesReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/product_sales.html"
    report_title = "Vendas por produto"
    report_slug = "relatorio-vendas-produtos"
    period_basis = "data de criação do pedido (somente pedidos prontos ou entregues)"

    def build(self, period):
        orders = list(orders_created_in(period, stage__in=[Order.Stage.READY, Order.Stage.DELIVERED]).prefetch_related("items"))
        products_map: dict[tuple, dict] = {}
        for order in orders:
            for item in order.items.all():
                category = _product_category(item)
                display_name = item.material_name or "Item sem nome"
                specs = [s for s in (item.product_color or "", f"Tam. {item.product_size}" if item.product_size else "") if s]
                if specs:
                    display_name += f" ({', '.join(specs)})"
                row = products_map.setdefault((category, display_name), {
                    "category": category, "badge_color": PRODUCT_CATEGORIES[category], "name": display_name,
                    "quantity": Decimal("0.00"), "meters": Decimal("0.00"), "revenue": Decimal("0.00"),
                    "discount": Decimal("0.00"), "orders_set": set(), "unit": item.billing_unit or "un",
                })
                row["quantity"] += Decimal(str(item.art_quantity if item.art_quantity else item.billing_quantity or 1))
                row["meters"] += item_meters(item)
                row["revenue"] += item.line_total
                row["discount"] += item.discount_total or Decimal("0.00")
                row["orders_set"].add(order.id)

        rows = list(products_map.values())
        for row in rows:
            row["orders_count"] = len(row["orders_set"])
            row["avg_price"] = (row["revenue"] / row["quantity"]) if row["quantity"] > 0 else Decimal("0.00")
        grand_total_revenue = sum((r["revenue"] for r in rows), Decimal("0.00"))
        grand_total_qty = sum((r["quantity"] for r in rows), Decimal("0.00"))
        grand_total_meters = sum((r["meters"] for r in rows), Decimal("0.00"))
        grand_total_discount = sum((r["discount"] for r in rows), Decimal("0.00"))
        rows.sort(key=lambda x: x["revenue"], reverse=True)
        for r in rows:
            r["percentage"] = (float(r["revenue"] / grand_total_revenue) * 100) if grand_total_revenue > 0 else 0.0
        return {
            "rows": rows,
            "grand_total_qty": grand_total_qty,
            "grand_total_meters": grand_total_meters,
            "grand_total_revenue": grand_total_revenue,
            "grand_total_discount": grand_total_discount,
            "total_orders_count": len(orders),
            "summary": [
                SummaryMetric("Faturamento", grand_total_revenue),
                SummaryMetric("Quantidade vendida", grand_total_qty, "number"),
                SummaryMetric("Descontos em camisas", grand_total_discount),
            ],
            "export_sections": [ExportSection(
                headers=["Categoria", "Produto / Item", "Qtd. Vendida", "Unidade", "Metros (m)", "Qtd. Pedidos", "Preço Médio (R$)", "Desconto por camisa (R$)", "Faturamento Total (R$)", "Participação (%)"],
                rows=[[r["category"], r["name"], r["quantity"], r["unit"], r["meters"], r["orders_count"], r["avg_price"], r["discount"], r["revenue"], f"{r['percentage']:.1f}%".replace(".", ",")] for r in rows],
                totals=["TOTAL GERAL", "", grand_total_qty, "", grand_total_meters, len(orders), "", grand_total_discount, grand_total_revenue, "100%"],
            )],
        }


class DailyConsumptionReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/daily_consumption.html"
    report_title = "Consumo diário"
    report_slug = "relatorio-consumo-diario"
    period_basis = "data de criação do pedido (somente pedidos prontos ou entregues)"

    def build(self, period):
        orders = orders_created_in(period, stage__in=[Order.Stage.READY, Order.Stage.DELIVERED]).prefetch_related("items").order_by("created_at")
        days_map = {
            day: {"date": day, "date_display": day.strftime("%d/%m/%Y"), "weekday": WEEKDAYS_SHORT[day.weekday()], "orders_count": 0,
                  "dtf_textil_meters": Decimal("0.00"), "dtf_uv_meters": Decimal("0.00"), "shirts_qty": 0, "services_qty": 0, "revenue": Decimal("0.00")}
            for day in iter_days(period)
        }
        totals = {"orders": 0, "textil": Decimal("0.00"), "uv": Decimal("0.00"), "shirts": 0, "services": 0, "revenue": Decimal("0.00")}
        for o in orders:
            d = days_map.get(timezone.localtime(o.created_at).date())
            if d is None:
                continue
            d["orders_count"] += 1
            d["revenue"] += o.total_amount
            totals["orders"] += 1
            totals["revenue"] += o.total_amount
            for item in o.items.all():
                mat_code = (item.material_code or "").lower()
                mat_name = (item.material_name or "").lower()
                kind = getattr(item, "kind", "")
                meters = item_meters(item)
                if "uv" in mat_code or "uv" in mat_name:
                    d["dtf_uv_meters"] += meters
                    totals["uv"] += meters
                elif mat_code == "dtf_textil" or kind == OrderItem.Kind.MATERIAL:
                    d["dtf_textil_meters"] += meters
                    totals["textil"] += meters
                elif kind == OrderItem.Kind.PRODUCT or "camisa" in mat_code or "camisa" in mat_name:
                    q = int(item.art_quantity or item.billing_quantity or 1)
                    d["shirts_qty"] += q
                    totals["shirts"] += q
                elif kind in {OrderItem.Kind.SERVICE, OrderItem.Kind.ADJUSTMENT} or "servico" in mat_code:
                    q = int(item.art_quantity or item.billing_quantity or 1)
                    d["services_qty"] += q
                    totals["services"] += q

        today = timezone.localdate()
        daily_rows = [v for _, v in sorted(days_map.items(), reverse=True) if v["orders_count"] > 0 or v["revenue"] > 0 or v["date"] <= today]
        return {
            "daily_rows": daily_rows,
            "grand_orders": totals["orders"],
            "grand_textil": totals["textil"],
            "grand_uv": totals["uv"],
            "grand_shirts": totals["shirts"],
            "grand_services": totals["services"],
            "grand_revenue": totals["revenue"],
            "summary": [
                SummaryMetric("Pedidos", totals["orders"], "number"),
                SummaryMetric("DTF Têxtil (m)", totals["textil"], "meters"),
                SummaryMetric("DTF UV (m)", totals["uv"], "meters"),
                SummaryMetric("Camisetas (un)", totals["shirts"], "number"),
                SummaryMetric("Faturamento", totals["revenue"]),
            ],
            "export_sections": [ExportSection(
                headers=["Data", "Dia da Semana", "Qtd. Pedidos", "DTF Têxtil (m)", "DTF UV (m)", "Camisetas (un)", "Serviços (un)", "Faturamento (R$)"],
                rows=[[r["date"], r["weekday"], r["orders_count"], r["dtf_textil_meters"], r["dtf_uv_meters"], r["shirts_qty"], r["services_qty"], r["revenue"]] for r in sorted(daily_rows, key=lambda x: x["date"])],
                totals=["TOTAL", "", totals["orders"], totals["textil"], totals["uv"], totals["shirts"], totals["services"], totals["revenue"]],
            )],
        }


class InkConsumptionReportView(LoginRequiredMixin, AdministratorRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/ink_consumption.html"
    report_title = "Consumo de tintas"
    report_slug = "relatorio-consumo-tintas"
    period_basis = "data da baixa de estoque (metros: data de criação dos pedidos prontos ou entregues)"

    def post(self, request, *args, **kwargs):
        """Baixa manual de tinta no estoque."""
        item_id = request.POST.get("item_id")
        raw_qty = request.POST.get("quantity", "1").replace(",", ".").strip()
        motivo = request.POST.get("motivo", "Consumo em Produção / Reposição de Tanque").strip()
        try:
            item = SupplyItem.objects.get(pk=item_id)
            qty = max(Decimal(raw_qty), Decimal("0.01"))
            prev = item.quantity
            item.quantity = max(Decimal("0.00"), item.quantity - qty)
            item.save(update_fields=["quantity", "updated_at"])
            SupplyMovement.objects.create(
                item=item,
                movement_type=SupplyMovement.MovementType.OUTPUT,
                quantity=qty,
                previous_quantity=prev,
                new_quantity=item.quantity,
                description=f"Baixa Manual de Tinta: {motivo}",
                user=request.user,
            )
            messages.success(request, f"Baixa de {qty} {item.get_unit_display()} em '{item.name}' realizada com sucesso!")
        except Exception as e:
            messages.error(request, f"Erro ao registrar baixa de tinta: {str(e)}")
        return redirect(request.get_full_path())

    def build(self, period):
        ink_items = SupplyItem.objects.filter(Q(name__icontains="tinta") | Q(name__icontains="verniz")).order_by("category", "name")
        movements = list(SupplyMovement.objects.filter(
            item__in=ink_items,
            movement_type=SupplyMovement.MovementType.OUTPUT,
            created_at__gte=period.start_at,
            created_at__lt=period.end_at,
        ).select_related("item", "user").order_by("-created_at"))
        textil_m = Decimal("0.00")
        uv_m = Decimal("0.00")
        for o in orders_created_in(period, stage__in=[Order.Stage.READY, Order.Stage.DELIVERED]).prefetch_related("items"):
            for it in o.items.all():
                mc = (it.material_code or "").lower()
                mn = (it.material_name or "").lower()
                if "uv" in mc or "uv" in mn:
                    uv_m += item_meters(it)
                elif mc == "dtf_textil" or getattr(it, "kind", "") == OrderItem.Kind.MATERIAL:
                    textil_m += item_meters(it)
        ink_summary = []
        for ink in ink_items:
            movs = [m for m in movements if m.item_id == ink.id]
            ink_summary.append({
                "item": ink,
                "current_stock": ink.quantity,
                "consumed": sum((m.quantity for m in movs), Decimal("0.00")),
                "unit": ink.get_unit_display(),
                "movements_count": len(movs),
            })
        total_consumed = sum((i["consumed"] for i in ink_summary), Decimal("0.00"))
        return {
            "ink_summary": ink_summary,
            "movements": movements,
            "textil_meters": textil_m,
            "uv_meters": uv_m,
            "total_consumed": total_consumed,
            "summary": [
                SummaryMetric("Tinta consumida", total_consumed, "number"),
                SummaryMetric("DTF Têxtil (m)", textil_m, "meters"),
                SummaryMetric("DTF UV (m)", uv_m, "meters"),
            ],
            "export_sections": [
                ExportSection(
                    title="Consumo por tinta",
                    headers=["Tinta / Verniz", "Estoque atual", "Consumido no período", "Unidade", "Baixas"],
                    rows=[[i["item"].name, i["current_stock"], i["consumed"], i["unit"], i["movements_count"]] for i in ink_summary],
                ),
                ExportSection(
                    title="Baixas de estoque",
                    headers=["Data/Hora", "Item", "Quantidade", "Descrição", "Responsável"],
                    rows=[[m.created_at, m.item.name, m.quantity, m.description, m.user.name if m.user else ""] for m in movements],
                ),
            ],
        }


class NewCustomersReportView(LoginRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/new_customers.html"
    report_title = "Clientes novos"
    report_slug = "clientes-novos"
    period_basis = "data de cadastro do cliente"

    def build(self, period):
        clientes_qs = Cliente.objects.filter(created_at__gte=period.start_at, created_at__lt=period.end_at).prefetch_related("pedidos_vinculados").order_by("-created_at")
        monthly: dict[tuple[int, int], dict] = {}
        current = period.start.replace(day=1)
        while current <= period.end:
            monthly[(current.year, current.month)] = {
                "month_num": current.month, "year": current.year, "month_name": f"{MONTH_NAMES[current.month]}/{current.year}",
                "new_clients_count": 0, "orders_count": 0, "total_spent": Decimal("0.00"),
            }
            current = date(current.year + (current.month // 12), current.month % 12 + 1, 1)

        clientes_data = []
        total_revenue_from_new = Decimal("0.00")
        total_orders_from_new = 0
        clients_with_orders_count = 0
        for cli in clientes_qs:
            created_local = timezone.localtime(cli.created_at)
            cli_orders = [o for o in cli.pedidos_vinculados.all() if o.stage != Order.Stage.CANCELLED]
            orders_count = len(cli_orders)
            total_spent = sum((o.total_amount for o in cli_orders), Decimal("0.00"))
            bucket = monthly.get((created_local.year, created_local.month))
            if bucket:
                bucket["new_clients_count"] += 1
                bucket["orders_count"] += orders_count
                bucket["total_spent"] += total_spent
            total_revenue_from_new += total_spent
            total_orders_from_new += orders_count
            clients_with_orders_count += 1 if orders_count else 0
            clientes_data.append({
                "cliente": cli,
                "created_at": cli.created_at,
                "orders_count": orders_count,
                "total_spent": total_spent,
                "paid_spent": sum((o.paid_amount for o in cli_orders), Decimal("0.00")),
                "has_special_price": bool(cli.preco_especial_metro or cli.preco_especial_dtf_uv),
            })
        return {
            "monthly_summary": list(monthly.values()),
            "clientes_data": clientes_data,
            "total_clients": len(clientes_data),
            "clients_with_orders_count": clients_with_orders_count,
            "total_orders_from_new": total_orders_from_new,
            "total_revenue_from_new": total_revenue_from_new,
            "summary": [
                SummaryMetric("Clientes novos", len(clientes_data), "number"),
                SummaryMetric("Clientes que compraram", clients_with_orders_count, "number"),
                SummaryMetric("Total comprado", total_revenue_from_new),
            ],
            "export_sections": [ExportSection(
                headers=["Data de Cadastro", "Nome", "CPF/CNPJ", "WhatsApp", "Preço DTF Têxtil", "Preço DTF UV", "Saldo Crédito", "Qtd Pedidos", "Total Comprado (R$)"],
                rows=[[
                    row["created_at"], row["cliente"].nome, row["cliente"].cpf_cnpj or "", row["cliente"].telefone or "",
                    row["cliente"].preco_especial_metro or "", row["cliente"].preco_especial_dtf_uv or "", row["cliente"].saldo_credito,
                    row["orders_count"], row["total_spent"],
                ] for row in clientes_data],
            )],
        }


PAYMENT_METHODS_DEF = {
    "pix": ("PIX", "fa-brands fa-pix", "#22c55e", "rgba(34, 197, 94, 0.15)"),
    "cartao_credito": ("Cartão de Crédito", "fa-solid fa-credit-card", "#38bdf8", "rgba(56, 189, 248, 0.15)"),
    "cartao_debito": ("Cartão de Débito", "fa-solid fa-id-card", "#818cf8", "rgba(129, 140, 248, 0.15)"),
    "cartao": ("Cartão (Geral)", "fa-solid fa-credit-card", "#60a5fa", "rgba(96, 165, 250, 0.15)"),
    "dinheiro": ("Dinheiro (À Vista)", "fa-solid fa-money-bill-wave", "#34d399", "rgba(52, 211, 153, 0.15)"),
    "transferencia": ("Transferência / TED", "fa-solid fa-building-columns", "#fbbf24", "rgba(251, 191, 36, 0.15)"),
    "saldo_credito": ("Saldo do Plano / Crédito", "fa-solid fa-wallet", "#c084fc", "rgba(192, 132, 252, 0.15)"),
    "outro": ("Outros / Diversos", "fa-solid fa-circle-question", "#9ca3af", "rgba(156, 163, 175, 0.15)"),
}


class PaymentMethodsReportView(LoginRequiredMixin, PeriodReportMixin, TemplateView):
    template_name = "reports/payment_methods.html"
    report_title = "Formas de pagamento"
    report_slug = "formas-pagamento"
    period_basis = "data de registro do pagamento (ou de criação do pedido, para pagamento único)"
    preserved_params = ("method",)

    def build(self, period):
        payments_qs = OrderPayment.objects.filter(created_at__gte=period.start_at, created_at__lt=period.end_at).select_related(
            "order", "order__cliente", "recorded_by"
        ).exclude(order__stage=Order.Stage.CANCELLED).order_by("-created_at")
        orders_without_splits = orders_created_in(period, paid_amount__gt=Decimal("0.00"), payments__isnull=True).exclude(
            stage=Order.Stage.CANCELLED
        ).select_related("cliente", "responsible", "payment_confirmed_by").order_by("-created_at")

        methods_def = {
            key: {"label": label, "icon": icon, "color": color, "badge_bg": bg, "total": Decimal("0.00"), "count": 0, "transactions": []}
            for key, (label, icon, color, bg) in PAYMENT_METHODS_DEF.items()
        }
        all_transactions = []

        def add(method, amount, item_data):
            method = method if method in methods_def else "outro"
            item_data.update({"method_key": method, "method_label": methods_def[method]["label"], "method_color": methods_def[method]["color"], "amount": amount})
            methods_def[method]["total"] += amount
            methods_def[method]["count"] += 1
            methods_def[method]["transactions"].append(item_data)
            all_transactions.append(item_data)

        for p in payments_qs:
            add(p.payment_method or "outro", p.amount, {
                "date": p.created_at, "order": p.order, "client_name": p.order.client_name,
                "notes": p.notes, "recorded_by": p.recorded_by.name if p.recorded_by else "—",
            })
        for o in orders_without_splits:
            add(o.payment_method or "outro", o.paid_amount or Decimal("0.00"), {
                "date": o.payment_confirmed_at or o.created_at, "order": o, "client_name": o.client_name,
                "notes": "Pagamento único registrado no pedido",
                "recorded_by": o.payment_confirmed_by.name if o.payment_confirmed_by else (o.responsible.name if o.responsible else "—"),
            })
        all_transactions.sort(key=lambda x: x["date"], reverse=True)
        grand_total = sum((t["amount"] for t in all_transactions), Decimal("0.00"))

        selected_method = self.request.GET.get("method", "").strip()
        if selected_method in methods_def:
            display_transactions = methods_def[selected_method]["transactions"]
        else:
            selected_method = ""
            display_transactions = all_transactions

        methods_list = []
        for key, val in methods_def.items():
            val["pct"] = round((val["total"] / grand_total * Decimal("100.0")) if grand_total > 0 else Decimal("0.0"), 1)
            val["avg"] = (val["total"] / Decimal(val["count"])) if val["count"] else Decimal("0.0")
            val["key"] = key
            methods_list.append(val)
        methods_list.sort(key=lambda x: x["total"], reverse=True)
        return {
            "methods_list": methods_list,
            "selected_method": selected_method,
            "grand_total": grand_total,
            "total_transactions_count": len(all_transactions),
            "transactions": display_transactions,
            "total_filtered_revenue": sum((t["amount"] for t in display_transactions), Decimal("0.00")),
            "summary": [
                SummaryMetric("Total recebido", grand_total),
                SummaryMetric("Transações", len(all_transactions), "number"),
            ],
            "export_sections": [ExportSection(
                headers=["Data/Hora", "Pedido", "Cliente", "Forma de Pagamento", "Valor (R$)", "Responsável", "Observação"],
                rows=[[t["date"], t["order"].number, t["client_name"], t["method_label"], t["amount"], t["recorded_by"], t["notes"]] for t in display_transactions],
            )],
        }
