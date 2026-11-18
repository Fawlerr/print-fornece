from django.db.models import Sum
from django.utils.functional import SimpleLazyObject

from .permissoes import conversas_visiveis, pode_usar_chat


def chat(request):
    """Menu do chat. O total de não lidas só é consultado se o template usar (cards do Kanban não usam)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not pode_usar_chat(user):
        return {"chat_disponivel": False, "chat_nao_lidas": 0}

    def _total() -> int:
        return conversas_visiveis(user).filter(arquivada_em__isnull=True).aggregate(t=Sum("nao_lidas"))["t"] or 0

    return {"chat_disponivel": True, "chat_nao_lidas": SimpleLazyObject(_total)}
