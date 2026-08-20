from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.SupplyListView.as_view(), name="list"),
    path("new/", views.SupplyCreateView.as_view(), name="create"),
    path("<int:pk>/edit/", views.SupplyUpdateView.as_view(), name="edit"),
    path("<int:pk>/movement/", views.SupplyQuickMovementView.as_view(), name="quick_movement"),
    path("<int:pk>/delete/", views.SupplyDeleteView.as_view(), name="delete"),
]
