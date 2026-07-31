from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def stone_webhook(request):
    """Reserved endpoint; it cannot alter an order or confirm payment."""
    return JsonResponse({"error": "Integração Stone ainda não habilitada."}, status=503)

