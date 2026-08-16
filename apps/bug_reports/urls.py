from django.urls import path

from . import views

app_name = "bug_reports"

urlpatterns = [
    path("", views.BugReportListView.as_view(), name="list"),
    path("submit/", views.BugReportCreateAjaxView.as_view(), name="submit"),
    path("<int:pk>/", views.BugReportDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.BugReportUpdateView.as_view(), name="edit"),
    path("<int:pk>/status/", views.BugReportDevStatusView.as_view(), name="update_status"),
]
