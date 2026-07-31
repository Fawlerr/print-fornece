"""Small CSP middleware, kept explicit until Django's CSP API is used project-wide."""
from __future__ import annotations

from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """Set a restrictive policy while allowing the two documented presentation CDNs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        policy = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdnjs.cloudflare.com data:; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "connect-src 'self'"
        )
        if not settings.DEBUG:
            response.headers.setdefault("Content-Security-Policy", policy)
        return response

