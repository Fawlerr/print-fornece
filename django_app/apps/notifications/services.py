from __future__ import annotations

from .models import Notification


def notify_user(user, title: str, message: str, link: str = "", notification_type: str = Notification.Type.ORDER) -> Notification:
    return Notification.objects.create(user=user, title=title, message=message, link=link, type=notification_type)


def notify_role(role: str, title: str, message: str, link: str = "", notification_type: str = Notification.Type.ORDER) -> int:
    from apps.accounts.models import User

    recipients = User.objects.filter(role=role, is_active=True).only("id")
    Notification.objects.bulk_create(
        [Notification(user=user, title=title, message=message, link=link, type=notification_type) for user in recipients]
    )
    return recipients.count()

