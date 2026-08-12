from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, UpdateView

from apps.notifications.services import notify_role
from apps.audit.services import record_audit

from .art_preview import generate_art_preview_image
from .calculator import CalculatorValidationError, calculate_quote, material_catalogue
from .forms import OrderForm
from .models import Order, OrderAttachment, OrderHistory, OrderStageHistory
from .pdf import generate_order_receipt_pdf
from .services import create_order, require_order_access, update_order


class OrderCreateView(LoginRequiredMixin, CreateView):
    template_name = "orders/form.html"
    form_class = OrderForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["calculator_materials"] = material_catalogue()
        context["calculator_endpoint"] = reverse("orders:calculate_quote")
        return context

    def form_valid(self, form):
        try:
            self.object = create_order(form=form, actor=self.request.user, files=self.request.FILES.getlist("attachments"), request=self.request)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Pedido {self.object.number} criado com sucesso.")
        if self.object.payment_status == Order.PaymentStatus.PAID:
            messages.info(self.request, "Pagamento confirmado. Gere o comprovante no detalhe do pedido.")
            return redirect("production:detail", pk=self.object.pk)
        return redirect("production:kanban")


class OrderUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "orders/form.html"
    form_class = OrderForm
    model = Order

    def get_queryset(self):
        return Order.objects.select_related("responsible", "created_by")

    def get_object(self, queryset=None):
        order = super().get_object(queryset)
        require_order_access(self.request.user, order)
        # ModelForm validation writes cleaned values onto this instance before
        # form_valid() runs, so retain the persisted state for payment history.
        self._previous_order_state = {
            "payment_status": order.payment_status,
            "paid_amount": str(order.paid_amount),
            "responsible_id": order.responsible_id,
        }
        return order

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            self.object = update_order(
                order=self.object,
                form=form,
                actor=self.request.user,
                files=self.request.FILES.getlist("attachments"),
                request=self.request,
                previous_state=getattr(self, "_previous_order_state", None),
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, "Pedido atualizado.")
        return redirect("production:detail", pk=self.object.pk)


def download_attachment(request, order_pk: int, pk: int):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
    attachment = get_object_or_404(OrderAttachment.objects.select_related("order"), pk=pk, order_id=order_pk, removed_at__isnull=True)
    require_order_access(request.user, attachment.order)
    if not attachment.file:
        raise Http404("Arquivo indisponível.")
    response = FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def download_receipt_pdf(request, pk: int):
    """Generate an order receipt/voucher PDF."""
    order = get_object_or_404(
        Order.objects.select_related("responsible", "created_by", "payment_confirmed_by").prefetch_related("items"),
        pk=pk,
    )
    token = request.GET.get("token")
    if not request.user.is_authenticated and token != str(order.quote_token):
        return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
    if request.user.is_authenticated:
        require_order_access(request.user, order)

    pdf_bytes = generate_order_receipt_pdf(order)
    if order.payment_status == Order.PaymentStatus.PAID and order.receipt_generated_at is None:
        order.receipt_generated_at = timezone.now()
        order.save(update_fields=["receipt_generated_at", "updated_at"])
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="comprovante_pedido_{order.number}.pdf"'
    return response


def calculate_order_quote(request):
    """Return an authenticated, server-authoritative calculator result."""
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Autenticação necessária."}, status=403)
    if request.method != "POST":
        return JsonResponse({"message": "Método não permitido."}, status=405)
    try:
        payload = json.loads(request.body or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"message": "Dados do orçamento inválidos."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"message": "Dados do orçamento inválidos."}, status=400)
    try:
        quote = calculate_quote(
            material_code=str(payload.get("material_code", "")),
            width_cm=payload.get("width_cm"),
            height_cm=payload.get("height_cm"),
            quantity=payload.get("quantity"),
        )
    except CalculatorValidationError as exc:
        return JsonResponse({"message": str(exc)}, status=422)
    return JsonResponse({"ok": True, "quote": quote.payload()})


def art_preview_view(request, pk: int):
    """Serve composite artwork preview image on gray background with watermark."""
    order = get_object_or_404(Order, pk=pk)
    token = request.GET.get("token")
    if not request.user.is_authenticated and token != str(order.quote_token):
        return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")

    attachment_id = request.GET.get("attachment_id")
    png_bytes = generate_art_preview_image(order, attachment_id=attachment_id)
    return HttpResponse(png_bytes, content_type="image/png")


def public_quote_view(request, token: str):
    """Public customer view for viewing and approving order quotes."""
    order = get_object_or_404(Order, quote_token=token)
    context = {
        "order": order,
        "token": token,
        "is_approved": order.stage not in (Order.Stage.NEW, Order.Stage.CANCELLED),
    }
    return render(request, "orders/public_quote.html", context)


def approve_quote_action(request, token: str):
    """Action for customer approving quote via public link."""
    if request.method != "POST":
        return redirect("orders:public_quote", token=token)
    
    order = get_object_or_404(Order, quote_token=token)
    
    if order.stage in (Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT):
        previous_stage = order.stage
        new_stage = Order.Stage.PAYMENT_CONFIRMED if order.payment_status == Order.PaymentStatus.PAID else Order.Stage.AWAITING_PAYMENT
        
        order.stage = new_stage
        order.stage_updated_at = timezone.now()
        order.save(update_fields=["stage", "stage_updated_at", "updated_at"])
        
        OrderStageHistory.objects.create(order=order, previous_stage=previous_stage, new_stage=new_stage, user=None)
        OrderHistory.objects.create(
            order=order,
            user=None,
            action="aprovacao_orcamento",
            description=f"Orçamento APROVADO pelo cliente via link público. Etapa avançada para {order.get_stage_display()}.",
        )
        record_audit(None, "aprovacao_orcamento", "pedido", order.pk, before={"etapa": previous_stage}, after={"etapa": new_stage}, request=request)
        notify_role("administrador", "Orçamento Aprovado! 🎉", f"O cliente aprovou o orçamento do pedido {order.number}.", f"/production/{order.pk}/")
        messages.success(request, "Orçamento aprovado com sucesso! A equipe já recebeu a confirmação.")
    else:
        messages.info(request, "Este orçamento já foi aprovado anteriormente.")

    return redirect("orders:public_quote", token=token)
