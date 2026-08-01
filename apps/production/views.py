from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, TemplateView

from apps.accounts.models import User
from apps.orders.forms import OrderFilterForm, OrderNoteForm
from apps.orders.models import Order, OrderAttachment, OrderHistory, OrderNote
from apps.orders.services import add_note as create_note
from apps.orders.services import remove_attachment as soft_remove_attachment
from apps.orders.services import require_order_access

from .services import cancel_order, finish_order, move_order_stage, restore_order


class KanbanView(LoginRequiredMixin, TemplateView):
    template_name = "production/kanban.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = OrderFilterForm(self.request.GET or None)
        orders = Order.objects.filter(stage__in=[Order.Stage.NEW, Order.Stage.PREPARATION, Order.Stage.PRODUCTION, Order.Stage.READY]).select_related("responsible").annotate(
            attachment_count=Count("attachments", filter=Q(attachments__removed_at__isnull=True))
        )
        if form.is_valid():
            data = form.cleaned_data
            if data.get("search"):
                term = data["search"]
                orders = orders.filter(Q(number__icontains=term) | Q(client_name__icontains=term) | Q(client_whatsapp__icontains=term))
            for field in ("stage", "payment_status", "priority"):
                if data.get(field):
                    orders = orders.filter(**{field: data[field]})
            if data.get("responsible"):
                orders = orders.filter(responsible_id=data["responsible"])
            orders = orders.order_by("-created_at" if data.get("order") == "newest" else "created_at")
        columns = {stage: [] for stage in (Order.Stage.NEW, Order.Stage.PREPARATION, Order.Stage.PRODUCTION, Order.Stage.READY)}
        for order in orders:
            columns[order.stage].append(order)
        context.update({
            "filter_form": form,
            "columns": columns,
            "stage_choices": Order.Stage.choices,
            "active_users": User.objects.filter(is_active=True).only("id", "name").order_by("name"),
        })
        return context


class OrderDetailView(LoginRequiredMixin, DetailView):
    template_name = "production/detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return Order.objects.select_related("responsible", "created_by", "cancelled_by").prefetch_related(
            Prefetch("attachments", queryset=OrderAttachment.objects.filter(removed_at__isnull=True).select_related("created_by")),
            Prefetch("notes", queryset=OrderNote.objects.select_related("user")),
            Prefetch("history", queryset=OrderHistory.objects.select_related("user")),
        )

    def get_object(self, queryset=None):
        order = super().get_object(queryset)
        require_order_access(self.request.user, order)
        return order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["note_form"] = OrderNoteForm()
        context["active_stages"] = [Order.Stage.NEW, Order.Stage.PREPARATION, Order.Stage.PRODUCTION, Order.Stage.READY]
        return context


def _order_for_request(request, pk: int) -> Order:
    order = get_object_or_404(Order, pk=pk)
    require_order_access(request.user, order)
    return order


@login_required
@require_POST
def move_stage(request, pk: int):
    new_stage = request.POST.get("stage")
    if request.content_type and request.content_type.startswith("application/json"):
        try:
            new_stage = json.loads(request.body or "{}").get("stage")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"message": "Dados inválidos."}, status=400)
    try:
        order = move_order_stage(order_id=pk, new_stage=new_stage or "", actor=request.user, request=request)
    except Order.DoesNotExist:
        return JsonResponse({"message": "Pedido não encontrado."}, status=404)
    except PermissionDenied:
        return JsonResponse({"message": "Acesso negado."}, status=403)
    except ValidationError as exc:
        return JsonResponse({"message": exc.messages[0]}, status=422)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or (request.content_type or "").startswith("application/json"):
        return JsonResponse({"ok": True, "stage": order.stage})
    messages.success(request, "Etapa atualizada.")
    return redirect("production:detail", pk=pk)


@login_required
@require_POST
def add_note(request, pk: int):
    order = _order_for_request(request, pk)
    form = OrderNoteForm(request.POST)
    if form.is_valid():
        create_note(order=order, text=form.cleaned_data["text"], actor=request.user, request=request)
        messages.success(request, "Observação adicionada.")
    else:
        messages.error(request, "Escreva uma observação antes de salvar.")
    return redirect("production:detail", pk=pk)


@login_required
@require_POST
def remove_attachment(request, pk: int, attachment_pk: int):
    order = _order_for_request(request, pk)
    attachment = get_object_or_404(OrderAttachment, pk=attachment_pk, order=order, removed_at__isnull=True)
    try:
        soft_remove_attachment(attachment=attachment, actor=request.user, request=request)
        messages.success(request, "Anexo removido do pedido.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("production:detail", pk=pk)


def _order_action(request, pk: int, action, success_message: str):
    try:
        action(order_id=pk, actor=request.user, request=request)
        messages.success(request, success_message)
    except Order.DoesNotExist:
        messages.error(request, "Pedido não encontrado.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("production:detail", pk=pk)


@login_required
@require_POST
def finalize(request, pk: int):
    return _order_action(request, pk, finish_order, "Pedido finalizado com sucesso.")


@login_required
@require_POST
def cancel(request, pk: int):
    return _order_action(request, pk, cancel_order, "Pedido cancelado.")


@login_required
@require_POST
def restore(request, pk: int):
    return _order_action(request, pk, restore_order, "Pedido restaurado para Pedido novo.")
