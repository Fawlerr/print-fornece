from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from apps.dashboard.views import home
from apps.reports.views import CashRegisterBetaView, CashRegisterReportView
from . import health, views

urlpatterns = [
    path("health/", health.health_check, name="health"),
    path("admin/", admin.site.urls),
    path("", home, name="home"),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("orders/", include("apps.orders.urls")),
    path("production/", include("apps.production.urls")),
    path("expenses/", include("apps.expenses.urls")),
    path("cash-register/", CashRegisterReportView.as_view(), name="cash_register_root"),
    path("cash-register/beta/", CashRegisterBetaView.as_view(), name="cash_register_beta_root"),
    path("caixa/", CashRegisterReportView.as_view(), name="caixa_root"),
    path("caixa/beta/", CashRegisterBetaView.as_view(), name="caixa_beta_root"),
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("payments/", include("apps.payments.urls")),
    path("bug-reports/", include("apps.bug_reports.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("backups/", include("apps.backups.urls")),
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]

handler400 = "config.views.error_400"
handler403 = "config.views.error_403"
handler404 = "config.views.error_404"
handler500 = "config.views.error_500"
