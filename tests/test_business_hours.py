"""A3 — horário de funcionamento: segunda a sexta, 8h às 17h; sábado e domingo fechado."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.business.hours import BusinessHours, get_business_hours
from apps.business.models import BusinessSettings
from apps.notifications.whatsapp import build_ready_whatsapp_message
from apps.orders.calculator import calculate_order_production_time
from apps.orders.models import Order

# Semana de referência: 09/11/2026 é segunda-feira.
MONDAY = date(2026, 11, 9)
FRIDAY = date(2026, 11, 13)
SATURDAY = date(2026, 11, 14)
SUNDAY = date(2026, 11, 15)
NEXT_MONDAY = date(2026, 11, 16)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class BusinessHoursTests(TestCase):
    def setUp(self):
        self.hours = get_business_hours()

    def test_default_is_monday_to_friday_8_to_17(self):
        self.assertEqual(self.hours.days, frozenset({0, 1, 2, 3, 4}))
        self.assertEqual((self.hours.opens, self.hours.closes), (time(8, 0), time(17, 0)))
        self.assertEqual(self.hours.describe(), "Seg a Sex: 8h às 17h · Sáb e Dom: fechado")

    def test_open_closed(self):
        self.assertTrue(self.hours.is_open(at(MONDAY, 8)))
        self.assertTrue(self.hours.is_open(at(FRIDAY, 16, 59)))
        self.assertFalse(self.hours.is_open(at(FRIDAY, 17)))
        self.assertFalse(self.hours.is_open(at(MONDAY, 7, 59)))
        self.assertFalse(self.hours.is_open(at(SATURDAY, 10)))
        self.assertFalse(self.hours.is_open(at(SUNDAY, 10)))

    def test_friday_16h_spills_to_monday(self):
        # 60 min úteis na sexta (16h–17h) + 30 min na segunda
        self.assertEqual(self.hours.add_business_minutes(at(FRIDAY, 16), 90), at(NEXT_MONDAY, 8, 30))
        self.assertEqual(self.hours.add_business_minutes(at(FRIDAY, 16), 30), at(FRIDAY, 16, 30))

    def test_friday_18h_starts_next_monday(self):
        self.assertEqual(self.hours.add_business_minutes(at(FRIDAY, 18), 30), at(NEXT_MONDAY, 8, 30))

    def test_saturday_and_sunday_start_on_monday(self):
        self.assertEqual(self.hours.add_business_minutes(at(SATURDAY, 10), 45), at(NEXT_MONDAY, 8, 45))
        self.assertEqual(self.hours.add_business_minutes(at(SUNDAY, 23, 50), 45), at(NEXT_MONDAY, 8, 45))

    def test_before_opening_starts_at_8(self):
        self.assertEqual(self.hours.add_business_minutes(at(MONDAY, 6), 60), at(MONDAY, 9))

    def test_multi_day_job(self):
        # 20h úteis a partir de segunda 8h = seg (9h) + ter (9h) + 2h na quarta
        self.assertEqual(self.hours.add_business_minutes(at(MONDAY, 8), 20 * 60), at(date(2026, 11, 11), 10))

    def test_subtract_business_minutes_skips_weekend(self):
        # 2 dias úteis antes de segunda 10h = quinta 10h
        self.assertEqual(self.hours.subtract_business_minutes(at(NEXT_MONDAY, 10), 2 * 9 * 60), at(date(2026, 11, 12), 10))

    def test_production_estimate_counts_only_business_hours(self):
        estimate = calculate_order_production_time(Decimal("4.00"), start_time=at(FRIDAY, 18), business_hours=self.hours)
        self.assertEqual(estimate["production_minutes"], 60)
        self.assertEqual(estimate["estimated_due_at"], at(NEXT_MONDAY, 9))

    def test_custom_hours_and_description(self):
        hours = BusinessHours(days=frozenset({0, 1, 2, 3, 4, 5}), opens=time(7, 30), closes=time(18, 0))
        self.assertEqual(hours.describe(), "Seg a Sáb: 7h30 às 18h · Dom: fechado")


class BusinessHoursIntegrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", name="Admin", password="strong-password", role=User.Role.ADMINISTRATOR)

    def test_whatsapp_uses_configured_hours_without_saturday(self):
        order = Order.objects.create(number="H-1", client_name="Cliente", client_whatsapp="84999999999", total_amount=Decimal("10"), created_by=self.admin)
        message = build_ready_whatsapp_message(order)
        self.assertIn("Seg a Sex: 8h às 17h", message)
        self.assertIn("Sáb e Dom: fechado", message)
        self.assertNotIn("Sáb: 8h às 12h", message)

    def test_admin_changes_hours_and_every_place_follows(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("business:settings"), {
            "section": "horario",
            "horario-business_days": ["0", "1", "2", "3", "4", "5"],
            "horario-business_open_time": "07:00",
            "horario-business_close_time": "16:00",
        })
        self.assertEqual(response.status_code, 302)
        config = BusinessSettings.load()
        self.assertEqual(config.business_days, [0, 1, 2, 3, 4, 5])
        order = Order.objects.create(number="H-2", client_name="Cliente", client_whatsapp="84999999999", total_amount=Decimal("10"), created_by=self.admin)
        self.assertIn("Seg a Sáb: 7h às 16h", build_ready_whatsapp_message(order))
        public = self.client.get(reverse("orders:public_quote", args=[order.quote_token]))
        self.assertContains(public, "Seg a Sáb: 7h às 16h")

    def test_settings_validation(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("business:settings"), {
            "section": "horario",
            "horario-business_days": ["0"],
            "horario-business_open_time": "17:00",
            "horario-business_close_time": "08:00",
        })
        self.assertContains(response, "O horário de fechamento deve ser depois da abertura.")

    def test_dashboard_idle_alert_uses_business_days(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "2 dias úteis")
