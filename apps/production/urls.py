from django.urls import path

from . import views

app_name = "production"
urlpatterns = [
    path("", views.KanbanView.as_view(), name="kanban"),
    path("<int:pk>/", views.OrderDetailView.as_view(), name="detail"),
    path("<int:pk>/stage/", views.move_stage, name="move_stage"),
    path("<int:pk>/notes/", views.add_note, name="add_note"),
    path("<int:pk>/attachments/add/", views.add_attachment, name="add_attachment"),
    path("<int:pk>/attachments/<int:attachment_pk>/remove/", views.remove_attachment, name="remove_attachment"),
    path("<int:pk>/finalize/", views.finalize, name="finalize"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("<int:pk>/restore/", views.restore, name="restore"),
]

