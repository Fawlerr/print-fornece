from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.dashboard.views import home
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
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("payments/", include("apps.payments.urls")),
    path("bug-reports/", include("apps.bug_reports.urls")),
]

handler400 = "config.views.error_400"
handler403 = "config.views.error_403"
handler404 = "config.views.error_404"
handler500 = "config.views.error_500"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
