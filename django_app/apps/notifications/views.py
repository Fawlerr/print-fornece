from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from .models import Notification


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 15

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


@login_required
def poll(request):
    return JsonResponse({"unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})


@login_required
@require_POST
def mark_read(request, pk: int):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return redirect(notification.link or reverse("notifications:list"))


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notifications:list")

