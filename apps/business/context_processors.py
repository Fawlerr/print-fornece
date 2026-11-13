from .models import BusinessSettings


def receipt_print(request):
    """Liga/desliga global da impressão automática da nota (A4), para o script do navegador."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {"receipt_print": {"enabled": BusinessSettings.load().auto_print_enabled}}
