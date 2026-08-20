from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, TemplateView

from apps.accounts.models import User
from apps.orders.forms import OrderFilterForm, OrderNoteForm
from apps.orders.models import Order, OrderAttachment, OrderHistory, OrderItem, OrderNote
from apps.orders.services import add_note as create_note
from apps.orders.services import remove_attachment as soft_remove_attachment
from apps.orders.services import require_order_access
from apps.notifications.whatsapp import get_whatsapp_share_links
from .capacity import get_daily_capacity_overview, evaluate_order_capacity

from .services import cancel_order, finish_order, move_order_stage, restore_order


class KanbanView(LoginRequiredMixin, TemplateView):
    template_name = "production/kanban.html"

    def get_context_data(self, **kwargs):
        from datetime import timedelta
        from django.utils import timezone

        context = super().get_context_data(**kwargs)
        user = self.request.user
        form = OrderFilterForm(self.request.GET or None)
        recent_delivered_cutoff = timezone.now() - timedelta(days=7)

        full_stages_list = [
            Order.Stage.NEW,
            Order.Stage.AWAITING_PAYMENT,
            Order.Stage.PAYMENT_CONFIRMED,
            Order.Stage.PRE_PRESS,
            Order.Stage.PRODUCTION,
            Order.Stage.READY,
            Order.Stage.DELIVERED,
        ]

        if getattr(user, "is_prepress_production_only", False):
            # Paula só vê a partir de Pré-Impressão
            active_stages_list = [
                Order.Stage.PRE_PRESS,
                Order.Stage.PRODUCTION,
                Order.Stage.READY,
                Order.Stage.DELIVERED,
            ]
        else:
            active_stages_list = full_stages_list

        orders = Order.objects.filter(
            Q(stage__in=active_stages_list) &
            (~Q(stage=Order.Stage.DELIVERED) | Q(stage=Order.Stage.DELIVERED, stage_updated_at__gte=recent_delivered_cutoff) | Q(stage=Order.Stage.DELIVERED, finished_at__gte=recent_delivered_cutoff) | Q(stage=Order.Stage.DELIVERED, created_at__gte=recent_delivered_cutoff))
        ).select_related("responsible").prefetch_related(
            Prefetch("attachments", queryset=OrderAttachment.objects.filter(removed_at__isnull=True)),
            Prefetch("items", queryset=OrderItem.objects.all()),
        ).annotate(
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

        columns = {stage: [] for stage in active_stages_list}
        for order in orders:
            if order.stage in columns:
                columns[order.stage].append(order)

        previous_next = {
            Order.Stage.NEW: (None, Order.Stage.AWAITING_PAYMENT),
            Order.Stage.AWAITING_PAYMENT: (Order.Stage.NEW, Order.Stage.PAYMENT_CONFIRMED),
            Order.Stage.PAYMENT_CONFIRMED: (Order.Stage.AWAITING_PAYMENT, Order.Stage.PRE_PRESS),
            Order.Stage.PRE_PRESS: (Order.Stage.PAYMENT_CONFIRMED if not getattr(user, "is_prepress_production_only", False) else None, Order.Stage.PRODUCTION),
            Order.Stage.PRODUCTION: (Order.Stage.PRE_PRESS, Order.Stage.READY),
            Order.Stage.READY: (Order.Stage.PRODUCTION, Order.Stage.DELIVERED),
            Order.Stage.DELIVERED: (Order.Stage.READY, None),
        }

        kanban_columns = []
        for stage in active_stages_list:
            is_locked = False
            if getattr(user, "is_attendance_sales_only", False) and stage in {Order.Stage.PRE_PRESS, Order.Stage.PRODUCTION}:
                is_locked = True

            label = Order.Stage(stage).label
            if stage == Order.Stage.DELIVERED:
                label = "Entregues (Últimos dias)"

            kanban_columns.append({
                "stage": stage,
                "label": label,
                "orders": columns[stage],
                "previous_stage": previous_next[stage][0],
                "next_stage": previous_next[stage][1],
                "finalize": stage == Order.Stage.READY,
                "is_locked": is_locked,
            })

        context.update({
            "filter_form": form,
            "columns": columns,
            "kanban_columns": kanban_columns,
            "stage_choices": Order.Stage.choices,
            "active_users": User.objects.filter(is_active=True).only("id", "name").order_by("name"),
            "daily_capacity": get_daily_capacity_overview(),
        })
        return context


class OrderDetailView(LoginRequiredMixin, DetailView):
    template_name = "production/detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return Order.objects.select_related("responsible", "created_by", "cancelled_by").prefetch_related(
            Prefetch("attachments", queryset=OrderAttachment.objects.filter(removed_at__isnull=True).select_related("created_by")),
            Prefetch("items", queryset=OrderItem.objects.all()),
            Prefetch("notes", queryset=OrderNote.objects.select_related("user")),
            Prefetch("history", queryset=OrderHistory.objects.select_related("user")),
        )

    def get_object(self, queryset=None):
        order = super().get_object(queryset)
        require_order_access(self.request.user, order)
        return order

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.object
        from apps.orders.forms import QuickPaymentForm
        context["note_form"] = OrderNoteForm()
        context["payment_form"] = QuickPaymentForm(initial={"paid_amount": f"{order.remaining_amount:.2f}".replace(".", ",")})
        context["active_stages"] = [
            Order.Stage.NEW,
            Order.Stage.AWAITING_PAYMENT,
            Order.Stage.PAYMENT_CONFIRMED,
            Order.Stage.PRE_PRESS,
            Order.Stage.PRODUCTION,
            Order.Stage.READY,
        ]
        order = self.object
        host = self.request.build_absolute_uri('/')[:-1]
        quote_url = f"{host}{reverse('orders:public_quote', kwargs={'token': order.quote_token})}"
        
        wa_links = get_whatsapp_share_links(order, host=host)
        context["whatsapp_links"] = wa_links
        context["whatsapp_share_url"] = wa_links["quote_url"]
        context["public_quote_url"] = quote_url
        context["capacity_warnings"] = evaluate_order_capacity(order=order)
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
def add_attachment(request, pk: int):
    order = _order_for_request(request, pk)
    files = request.FILES.getlist("attachments")
    if not files:
        messages.error(request, "Selecione ao menos um arquivo para anexar.")
        return redirect("production:detail", pk=pk)
    try:
        from apps.orders.services import save_order_attachments
        count = save_order_attachments(order=order, files=files, actor=request.user, request=request)
        messages.success(request, f"{count} anexo(s) adicionado(s) com sucesso ao pedido.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
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


@login_required
@require_POST
def mark_whatsapp_notified(request, pk: int):
    order = _order_for_request(request, pk)
    order.notified_whatsapp = True
    order.notified_whatsapp_at = timezone.now()
    order.notified_whatsapp_by = request.user
    order.save(update_fields=["notified_whatsapp", "notified_whatsapp_at", "notified_whatsapp_by", "updated_at"])

    user_display = request.user.name or request.user.email
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action="cliente_avisado_whatsapp",
        description=f"Cliente avisado no WhatsApp por {user_display}.",
    )
    from apps.audit.services import record_audit
    record_audit(
        request.user,
        "notificacao_whatsapp",
        "pedido",
        order.pk,
        after={"notified_whatsapp": True, "by": user_display, "at": order.notified_whatsapp_at.isoformat()},
        request=request,
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or (request.content_type or "").startswith("application/json"):
        return JsonResponse({"ok": True, "message": "Cliente marcado como avisado!"})
    messages.success(request, f"Cliente marcado como avisado no WhatsApp ({user_display}).")
    return redirect("production:detail", pk=pk)
