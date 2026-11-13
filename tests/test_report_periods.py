"""A2 — período personalizado, atalhos, comparação e exportação em todos os relatórios."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import SystemSetting, User
from apps.orders.models import Order
from apps.reports.periods import ReportPeriod, preset_range, resolve_period, variation_percent

REPORT_ROUTES = [
    "reports:index", "reports:production", "reports:materials", "reports:team_ranking", "reports:customers_ranking",
    "reports:product_sales", "reports:daily_consumption", "reports:ink_consumption", "reports:new_customers",
    "reports:payment_methods", "reports:cash_register",
]


def local_dt(day: date, at: time) -> datetime:
    return timezone.make_aware(datetime.combine(day, at))


class PeriodUnitTests(TestCase):
    def test_end_day_is_fully_included(self):
        period = ReportPeriod(date(2026, 11, 1), date(2026, 11, 10))
        self.assertEqual(period.start_at, local_dt(date(2026, 11, 1), time.min))
        self.assertEqual(period.end_at, local_dt(date(2026, 11, 11), time.min))  # fim exclusivo
        self.assertLess(local_dt(date(2026, 11, 10), time(23, 59, 59)), period.end_at)
        self.assertEqual(period.label, "01/11/2026 a 10/11/2026")
        self.assertEqual(period.days, 10)

    def test_presets(self):
        today = date(2026, 11, 12)
        self.assertEqual(preset_range("hoje", today), (today, today))
        self.assertEqual(preset_range("ontem", today), (date(2026, 11, 11), date(2026, 11, 11)))
        self.assertEqual(preset_range("7d", today), (date(2026, 11, 6), today))
        self.assertEqual(preset_range("30d", today), (date(2026, 10, 14), today))
        self.assertEqual(preset_range("este_mes", today), (date(2026, 11, 1), today))
        self.assertEqual(preset_range("mes_passado", today), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(preset_range("este_ano", today), (date(2026, 1, 1), today))

    def test_last_month_in_january_goes_to_previous_year(self):
        self.assertEqual(preset_range("mes_passado", date(2027, 1, 15)), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_previous_equivalent_period(self):
        # Este mês (1 a 12) x mesmo trecho do mês passado
        self.assertEqual(ReportPeriod(date(2026, 11, 1), date(2026, 11, 12)).previous(), ReportPeriod(date(2026, 10, 1), date(2026, 10, 12)))
        # Mês completo x mês anterior completo (inclusive com 31 x 30 dias)
        self.assertEqual(ReportPeriod(date(2026, 10, 1), date(2026, 10, 31)).previous(), ReportPeriod(date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(ReportPeriod(date(2026, 3, 1), date(2026, 3, 31)).previous(), ReportPeriod(date(2026, 2, 1), date(2026, 2, 28)))
        # Janeiro x dezembro do ano anterior
        self.assertEqual(ReportPeriod(date(2027, 1, 1), date(2027, 1, 31)).previous(), ReportPeriod(date(2026, 12, 1), date(2026, 12, 31)))
        # Intervalo qualquer: mesma quantidade de dias imediatamente antes
        self.assertEqual(ReportPeriod(date(2026, 11, 6), date(2026, 11, 12)).previous(), ReportPeriod(date(2026, 10, 30), date(2026, 11, 5)))

    def test_invalid_custom_period_returns_error_and_default(self):
        period, error = resolve_period(QueryDict("inicio=2026-11-20&fim=2026-11-01"), "hoje")
        self.assertEqual(error, "A data inicial não pode ser maior que a data final.")
        self.assertEqual(period.preset, "hoje")
        _period, error = resolve_period(QueryDict("inicio=2026-11-01&fim=lixo"), "hoje")
        self.assertIn("formato correto", error)
        _period, error = resolve_period(QueryDict("inicio=2010-01-01&fim=2026-01-01"), "hoje")
        self.assertIn("5 anos", error)

    def test_clicked_preset_wins_over_form_dates(self):
        period, error = resolve_period(QueryDict("periodo=ontem&inicio=2026-01-01&fim=2026-01-31"), "hoje")
        self.assertEqual(error, "")
        self.assertEqual(period.preset, "ontem")
        period, _ = resolve_period(QueryDict("periodo=personalizado&inicio=2026-01-01&fim=2026-01-31"), "hoje")
        self.assertEqual((period.start, period.end), (date(2026, 1, 1), date(2026, 1, 31)))

    def test_legacy_params_still_work(self):
        self.assertEqual(resolve_period(QueryDict("month=2026-10"))[0], ReportPeriod(date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(resolve_period(QueryDict("year=2026&month=2"))[0], ReportPeriod(date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(resolve_period(QueryDict("year=2025&month=todos"))[0], ReportPeriod(date(2025, 1, 1), date(2025, 12, 31)))
        self.assertEqual(resolve_period(QueryDict("date=2026-11-05"))[0], ReportPeriod(date(2026, 11, 5), date(2026, 11, 5)))
        self.assertEqual(resolve_period(QueryDict("start=2026-11-01&end=2026-11-03"))[0], ReportPeriod(date(2026, 11, 1), date(2026, 11, 3)))

    def test_variation_percent(self):
        self.assertEqual(variation_percent(Decimal("150"), Decimal("100")), 50.0)
        self.assertEqual(variation_percent(50, 100), -50.0)
        self.assertIsNone(variation_percent(10, 0))


class ReportPeriodViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", name="Admin", password="strong-password", role=User.Role.ADMINISTRATOR)
        SystemSetting.objects.update_or_create(key="cash_register", defaults={"name": "Caixa", "is_active": True})
        self.client.force_login(self.admin)

    def _order(self, number, created_at, total="100.00", **extra):
        order = Order.objects.create(number=number, client_name=f"Cliente {number}", client_whatsapp="84999999999",
                                     total_amount=Decimal(total), paid_amount=Decimal(total), payment_status=Order.PaymentStatus.PAID,
                                     created_by=self.admin, **extra)
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        return order

    def test_boundaries_include_whole_last_day_and_exclude_next_day(self):
        self._order("B-1", local_dt(date(2026, 10, 1), time(0, 0)))
        self._order("B-2", local_dt(date(2026, 10, 31), time(23, 59, 59)))
        self._order("B-3", local_dt(date(2026, 11, 1), time(0, 0)))
        self._order("B-0", local_dt(date(2026, 9, 30), time(23, 59, 59)))
        response = self.client.get(reverse("reports:index"), {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-10-31"})
        numbers = {o.number for o in response.context["orders"]}
        self.assertEqual(numbers, {"B-1", "B-2"})
        self.assertContains(response, "01/10/2026 a 31/10/2026")
        self.assertContains(response, "Período baseado na data de criação do pedido")

    def test_invalid_period_shows_visible_error(self):
        response = self.client.get(reverse("reports:index"), {"periodo": "personalizado", "inicio": "2026-10-31", "fim": "2026-10-01"})
        self.assertContains(response, "A data inicial não pode ser maior que a data final.")

    def test_every_report_accepts_period_and_exports_all_formats(self):
        self._order("E-1", local_dt(date(2026, 10, 15), time(10, 0)), stage=Order.Stage.DELIVERED)
        params = {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-10-31"}
        for route in REPORT_ROUTES:
            with self.subTest(route=route):
                page = self.client.get(reverse(route), params)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, "01/10/2026 a 31/10/2026")
                csv_resp = self.client.get(reverse(route), {**params, "export": "csv"})
                self.assertEqual(csv_resp["Content-Type"], "text/csv; charset=utf-8")
                self.assertIn("20261001-20261031", csv_resp["Content-Disposition"])
                xlsx = self.client.get(reverse(route), {**params, "export": "xlsx"})
                self.assertEqual(xlsx["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.assertTrue(xlsx.content.startswith(b"PK"))
                pdf = self.client.get(reverse(route), {**params, "export": "pdf"})
                self.assertEqual(pdf["Content-Type"], "application/pdf")
                self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_export_respects_period(self):
        self._order("IN-1", local_dt(date(2026, 10, 15), time(10, 0)))
        self._order("OUT-1", local_dt(date(2026, 9, 15), time(10, 0)))
        csv_text = self.client.get(reverse("reports:index"), {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-10-31", "export": "csv"}).content.decode("utf-8")
        self.assertIn("IN-1", csv_text)
        self.assertNotIn("OUT-1", csv_text)

    def test_compare_with_previous_period(self):
        self._order("C-1", local_dt(date(2026, 10, 10), time(10, 0)), total="150.00")
        self._order("C-0", local_dt(date(2026, 9, 10), time(10, 0)), total="100.00")
        response = self.client.get(reverse("reports:index"), {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-10-31", "comparar": "1"})
        rows = {row["label"]: row for row in response.context["comparison"]}
        self.assertEqual(rows["Faturamento pago"]["current"], Decimal("150.00"))
        self.assertEqual(rows["Faturamento pago"]["previous"], Decimal("100.00"))
        self.assertEqual(rows["Faturamento pago"]["variation"], 50.0)
        self.assertContains(response, "01/09/2026 a 30/09/2026")

    def test_period_is_kept_when_navigating_between_reports(self):
        self.client.get(reverse("reports:index"), {"periodo": "mes_passado"})
        response = self.client.get(reverse("reports:materials"))
        self.assertEqual(response.context["period"].preset, "mes_passado")
        self.assertContains(response, "?periodo=mes_passado")  # links das abas carregam o período

    def test_cash_register_defaults_to_today_and_accepts_period(self):
        self.client.get(reverse("reports:index"), {"periodo": "mes_passado"})
        response = self.client.get(reverse("reports:cash_register"))
        self.assertEqual(response.context["period"].preset, "hoje")
        response = self.client.get(reverse("reports:cash_register"), {"periodo": "7d"})
        self.assertEqual(response.context["period"].days, 7)

    def test_customers_ranking_now_respects_period(self):
        self._order("R-IN", local_dt(date(2026, 10, 10), time(10, 0)))
        self._order("R-OUT", local_dt(date(2025, 1, 10), time(10, 0)))
        response = self.client.get(reverse("reports:customers_ranking"), {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-10-31"})
        names = {row["name"] for row in response.context["customer_rows"]}
        self.assertEqual(names, {"Cliente R-IN"})

    def test_presets_use_project_timezone_today(self):
        fixed = date(2027, 1, 15)
        with mock.patch("apps.reports.periods.timezone.localdate", return_value=fixed):
            response = self.client.get(reverse("reports:index"), {"periodo": "mes_passado"})
        self.assertEqual(response.context["period"], ReportPeriod(date(2026, 12, 1), date(2026, 12, 31), "mes_passado"))

    def test_long_period_still_works(self):
        start = timezone.localdate() - timedelta(days=365 * 3)
        response = self.client.get(reverse("reports:production"), {"periodo": "personalizado", "inicio": start.isoformat(), "fim": timezone.localdate().isoformat()})
        self.assertEqual(response.status_code, 200)
