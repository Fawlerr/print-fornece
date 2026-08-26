from django.urls import path
from . import views

app_name = "backups"

urlpatterns = [
    path("", views.BackupListView.as_view(), name="list"),
    path("create/", views.BackupCreateView.as_view(), name="create"),
    path("download/<int:pk>/", views.BackupDownloadView.as_view(), name="download"),
    path("delete/<int:pk>/", views.BackupDeleteView.as_view(), name="delete"),
]
