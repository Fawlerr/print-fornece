from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Keep imported/demo accounts on the password screen until they set a new password."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.force_password_change:
            allowed = {
                reverse("accounts:change_password"),
                reverse("accounts:logout"),
            }
            if request.path not in allowed and not request.path.startswith("/admin/"):
                return redirect("accounts:change_password")
        return self.get_response(request)

