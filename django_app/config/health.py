from django.http import JsonResponse


def health_check(request):
    """Liveness check: intentionally exposes no version, settings or database data."""
    return JsonResponse({"status": "ok"})
