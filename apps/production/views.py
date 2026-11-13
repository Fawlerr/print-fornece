from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
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


FULL_KANBAN_STAGES = [
    Order.Stage.NEW,
    Order.Stage.AWAITING_PAYMENT,
    Order.Stage.PAYMENT_CONFIRMED,
    Order.Stage.PRE_PRESS,
    Order.Stage.PRODUCTION,
    Order.Stage.READY,
    Order.Stage.DELIVERED,
]


def kanban_stage_config(user) -> tuple[list[str], dict]:
    """Colunas visíveis para o usuário e a etapa anterior/seguinte de cada coluna."""
    is_prepress_only = getattr(user, "is_prepress_production_only", False)
    if is_prepress_only:
        # Paula vê a partir de Pagamento Confirmado
        stages = FULL_KANBAN_STAGES[2:]
    else:
        stages = list(FULL_KANBAN_STAGES)
    neighbors = {
        Order.Stage.NEW: (None, Order.Stage.AWAITING_PAYMENT),
        Order.Stage.AWAITING_PAYMENT: (Order.Stage.NEW, Order.Stage.PAYMENT_CONFIRMED),
        Order.Stage.PAYMENT_CONFIRMED: (None if is_prepress_only else Order.Stage.AWAITING_PAYMENT, Order.Stage.PRE_PRESS),
        Order.Stage.PRE_PRESS: (Order.Stage.PAYMENT_CONFIRMED, Order.Stage.PRODUCTION),
        Order.Stage.PRODUCTION: (Order.Stage.PRE_PRESS, Order.Stage.READY),
        Order.Stage.READY: (Order.Stage.PRODUCTION, Order.Stage.DELIVERED),
        Order.Stage.DELIVERED: (Order.Stage.READY, None),
    }
    return stages, neighbors


def kanban_cards_queryset():
    return Order.objects.select_related("responsible", "notified_whatsapp_by").prefetch_related(
        Prefetch("attachments", queryset=OrderAttachment.objects.filter(removed_at__isnull=True)),
        Prefetch("items", queryset=OrderItem.objects.all()),
    ).annotate(
        attachment_count=Count("attachments", filter=Q(attachments__removed_at__isnull=True))
    )


class KanbanView(LoginRequiredMixin, TemplateView):
    template_name = "production/kanban.html"

    def get_context_data(self, **kwargs):
        from datetime import timedelta
        from django.utils import timezone

        context = super().get_context_data(**kwargs)
        user = self.request.user
        form = OrderFilterForm(self.request.GET or None)
        recent_delivered_cutoff = timezone.now() - timedelta(days=7)

        active_stages_list, previous_next = kanban_stage_config(user)

        orders = kanban_cards_queryset().filter(
            Q(stage__in=active_stages_list) &
            (~Q(stage=Order.Stage.DELIVERED) | Q(stage=Order.Stage.DELIVERED, stage_updated_at__gte=recent_delivered_cutoff) | Q(stage=Order.Stage.DELIVERED, finished_at__gte=recent_delivered_cutoff) | Q(stage=Order.Stage.DELIVERED, created_at__gte=recent_delivered_cutoff))
        )
        if form.is_valid():
            data = form.cleaned_data
            if data.get("search"):
                term = data["search"]
                orders = orders.filter(Q(number__icontains=term) | Q(client_name__icontains=term) | Q(client_whatsapp__icontains=term))
            for field in ("stage", "payment_status", "priority"):
                if data.get(field):
                    orders = orders.filter(**{field: data[field]})
            if data.get("material_type"):
                mat = data["material_type"]
                if mat == "dtf_uv":
                    orders = orders.filter(
                        Q(items__material_code__icontains="uv") |
                        Q(items__material_name__icontains="uv") |
                        (Q(items__isnull=True) & Q(description__icontains="uv"))
                    ).distinct()
                elif mat == "dtf_textil":
                    orders = orders.filter(
                        (Q(items__material_code="dtf_textil") |
                         Q(items__material_name__icontains="textil") |
                         Q(items__material_name__icontains="têxtil") |
                         (Q(items__isnull=True) & ~Q(description__icontains="uv")))
                        & ~Q(items__material_code__icontains="uv")
                    ).distinct()
            if data.get("responsible"):
                orders = orders.filter(responsible_id=data["responsible"])
            orders = orders.order_by("-created_at" if data.get("order") == "newest" else "created_at")

        columns = {stage: [] for stage in active_stages_list}
        for order in orders:
            if order.stage in columns:
                columns[order.stage].append(order)

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
            "kanban_now": timezone.now().isoformat(),
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
        from apps.business.models import BusinessSettings
        context["cancellation_pin_configured"] = BusinessSettings.load().has_cancellation_pin
        return context


@login_required
def kanban_updates(request):
    """A6: cards alterados desde ``since`` (polling curto do Kanban, sem recarregar a página).

    Devolve o HTML do card já renderizado, para atualizar selos (ex.: APROVADO),
    pagamento e coluna em tempo real.
    """
    from datetime import datetime, timedelta

    from django.template.loader import render_to_string

    now = timezone.now()
    since = None
    raw = (request.GET.get("since") or "").strip().replace(" ", "+")
    if raw:
        try:
            since = datetime.fromisoformat(raw)
            if timezone.is_naive(since):
                since = timezone.make_aware(since)
        except ValueError:
            since = None
    if since is None or since < now - timedelta(hours=1):
        since = now - timedelta(minutes=2)

    stages, neighbors = kanban_stage_config(request.user)
    payload = []
    for order in kanban_cards_queryset().filter(updated_at__gt=since).order_by("updated_at")[:100]:
        visible = order.stage in stages
        html = ""
        if visible:
            previous_stage, next_stage = neighbors.get(order.stage, (None, None))
            html = render_to_string("production/_kanban_card.html", {
                "order": order,
                "previous_stage": previous_stage,
                "next_stage": next_stage,
                "finalize": order.stage == Order.Stage.READY,
            }, request=request)
        payload.append({"id": order.pk, "stage": order.stage, "visible": visible, "html": html})
    return JsonResponse({"now": now.isoformat(), "orders": payload})


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
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.headers.get("Accept") == "application/json"
    if not files:
        if is_ajax:
            return JsonResponse({"success": False, "errors": ["Selecione ao menos um arquivo para anexar."]}, status=400)
        messages.error(request, "Selecione ao menos um arquivo para anexar.")
        return redirect("production:detail", pk=pk)
    try:
        from apps.orders.services import save_order_attachments
        count = save_order_attachments(order=order, files=files, actor=request.user, request=request)
        msg = f"{count} anexo(s) adicionado(s) com sucesso ao pedido."
        messages.success(request, msg)
        if is_ajax:
            return JsonResponse({"success": True, "redirect_url": reverse("production:detail", kwargs={"pk": pk}), "message": msg})
    except ValidationError as exc:
        if is_ajax:
            return JsonResponse({"success": False, "errors": [exc.messages[0]]}, status=400)
        messages.error(request, exc.messages[0])
    return redirect("production:detail", pk=pk)


@login_required
@require_POST
def remove_attachment(request, pk: int, attachment_pk: int):
    order = _order_for_request(request, pk)
    attachment = get_object_or_404(OrderAttachment, pk=attachment_pk, order=order, removed_at__isnull=True)
    reason = request.POST.get("removal_reason") or request.POST.get("reason", "").strip()
    try:
        soft_remove_attachment(attachment=attachment, actor=request.user, reason=reason, request=request)
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
    reason = (request.POST.get("cancellation_reason") or request.POST.get("reason", "")).strip()
    pin = request.POST.get("cancellation_pin", "")
    try:
        cancel_order(order_id=pk, actor=request.user, reason=reason, pin=pin, request=request)
        messages.success(request, "Pedido cancelado com sucesso.")
    except Order.DoesNotExist:
        messages.error(request, "Pedido não encontrado.")
    except PermissionDenied:
        messages.error(request, "Você não tem permissão para cancelar este pedido.")
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect("production:detail", pk=pk)


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
