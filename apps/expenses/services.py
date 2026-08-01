from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit

from .models import Expense


@transaction.atomic
def cancel_expense(*, expense: Expense, actor, request=None) -> Expense:
    if expense.status != Expense.Status.ACTIVE:
        raise ValidationError("Despesa não encontrada ou já cancelada.")
    expense.status = Expense.Status.CANCELLED
    expense.cancelled_at = timezone.now()
    expense.cancelled_by = actor
    expense.save(update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"])
    record_audit(actor, "cancelamento", "despesa", expense.pk, before={"status": Expense.Status.ACTIVE}, after={"status": Expense.Status.CANCELLED}, request=request)
    return expense

