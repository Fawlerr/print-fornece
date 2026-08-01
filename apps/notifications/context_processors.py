from .models import Notification


def navigation_notifications(request):
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0, "recent_notifications": []}
    notifications = Notification.objects.filter(user=request.user)
    return {
        "unread_notification_count": notifications.filter(read_at__isnull=True).count(),
        "recent_notifications": notifications[:5],
    }

