from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from apps.accounts.permissions import AdministratorRequiredMixin, require_administrator
from apps.audit.services import record_audit

from .forms import ExpenseForm
from .models import Expense
from .services import cancel_expense


def _date_value(value, default):
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


class ExpenseListView(LoginRequiredMixin, AdministratorRequiredMixin, ListView):
    template_name = "expenses/list.html"
    context_object_name = "expenses"

    def get_queryset(self):
        self.start = _date_value(self.request.GET.get("start"), timezone.localdate().replace(day=1))
        self.end = _date_value(self.request.GET.get("end"), timezone.localdate())
        self.category = self.request.GET.get("category", "")
        queryset = Expense.objects.select_related("created_by").filter(expense_date__range=(self.start, self.end))
        if self.category in Expense.Category.values:
            queryset = queryset.filter(category=self.category)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "start": self.start,
            "end": self.end,
            "category": self.category,
            "categories": Expense.Category.choices,
            "total": self.object_list.filter(status=Expense.Status.ACTIVE).aggregate(total=Sum("amount"))["total"] or 0,
        })
        return context


class ExpenseCreateView(LoginRequiredMixin, AdministratorRequiredMixin, CreateView):
    template_name = "expenses/form.html"
    form_class = ExpenseForm
    success_url = reverse_lazy("expenses:list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        record_audit(self.request.user, "criacao", "despesa", self.object.pk, after={"descricao": self.object.description, "valor": str(self.object.amount)}, request=self.request)
        messages.success(self.request, "Despesa adicionada.")
        return response


class ExpenseUpdateView(LoginRequiredMixin, AdministratorRequiredMixin, UpdateView):
    template_name = "expenses/form.html"
    form_class = ExpenseForm
    model = Expense
    success_url = reverse_lazy("expenses:list")

    def form_valid(self, form):
        before = {"descricao": self.object.description, "valor": str(self.object.amount)}
        response = super().form_valid(form)
        record_audit(self.request.user, "edicao", "despesa", self.object.pk, before=before, after={"descricao": self.object.description, "valor": str(self.object.amount)}, request=self.request)
        messages.success(self.request, "Despesa atualizada.")
        return response


@login_required
@require_POST
def cancel(request, pk: int):
    require_administrator(request.user)
    expense = get_object_or_404(Expense, pk=pk)
    try:
        cancel_expense(expense=expense, actor=request.user, request=request)
        messages.success(request, "Despesa cancelada.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("expenses:list")

