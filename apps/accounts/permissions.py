from __future__ import annotations

from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class AdministratorRequiredMixin(UserPassesTestMixin):
    """Return a proper 403 instead of silently redirecting unauthorized users."""

    def test_func(self):
        return bool(self.request.user.is_authenticated and self.request.user.is_administrator)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied("Esta área é restrita a administradores.")
        return super().handle_no_permission()


def require_administrator(user) -> None:
    if not user.is_authenticated or not user.is_administrator:
        raise PermissionDenied("Esta ação exige perfil de administrador.")

