from __future__ import annotations

from typing import Any

from .models import AuditEvent


def record_audit(user, action: str, entity: str, entity_id: int | None = None, before: Any = None, after: Any = None, request=None) -> AuditEvent:
    """Create an audit record without serializing secrets or request bodies."""
    address = None
    user_agent = ""
    if request is not None:
        address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
    return AuditEvent.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before=before,
        after=after,
        ip=address or None,
        user_agent=user_agent,
    )

