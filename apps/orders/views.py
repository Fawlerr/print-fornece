from __future__ import annotations

import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, UpdateView

from apps.notifications.services import notify_role
from apps.notifications.whatsapp import get_whatsapp_share_links
from apps.audit.services import record_audit

from .art_preview import generate_art_preview_image
from .calculator import (
    CalculatorValidationError,
    calculate_quote,
    calculate_shirt_quote,
    calculate_service_quote,
    material_catalogue,
    full_catalogue,
)
from .forms import OrderForm
from .models import Order, OrderAttachment, OrderHistory, OrderItem, OrderStageHistory
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
        context["catalogue"] = full_catalogue()
        context["calculator_endpoint"] = reverse("orders:calculate_quote")
        existing_items = []
        if self.request.POST.get("calculation_payload"):
            try:
                posted_data = json.loads(self.request.POST.get("calculation_payload"))
                if isinstance(posted_data, dict) and "items" in posted_data:
                    existing_items = posted_data["items"]
                elif isinstance(posted_data, list):
                    existing_items = posted_data
            except Exception:
                pass
        context["existing_items"] = existing_items
        return context

    def form_valid(self, form):
        is_ajax = self.request.headers.get("X-Requested-With") == "XMLHttpRequest" or self.request.headers.get("Accept") == "application/json"
        try:
            self.object = create_order(form=form, actor=self.request.user, files=self.request.FILES.getlist("attachments"), request=self.request)
        except ValidationError as exc:
            if is_ajax:
                return JsonResponse({"success": False, "errors": [exc.messages[0]]}, status=400)
            form.add_error(None, exc.messages[0])
            return self.form_invalid(form)

        messages.success(self.request, f"Pedido {self.object.number} criado com sucesso.")
        if self.object.payment_status == Order.PaymentStatus.PAID:
            messages.info(self.request, "Pagamento confirmado. Gere o comprovante no detalhe do pedido.")
            redirect_url = reverse("production:detail", kwargs={"pk": self.object.pk})
        else:
            redirect_url = reverse("production:kanban")

        # Geração automática do link do WhatsApp para envio do orçamento
        host = self.request.build_absolute_uri('/')[:-1]
        share_links = get_whatsapp_share_links(self.object, host=host)
        whatsapp_quote_url = share_links.get("quote_url") if share_links.get("phone") else ""

        if is_ajax:
            return JsonResponse({
                "success": True,
                "redirect_url": redirect_url,
                "order_number": self.object.number,
                "whatsapp_quote_url": whatsapp_quote_url,
            })
        if whatsapp_quote_url:
            self.request.session["auto_open_whatsapp_url"] = whatsapp_quote_url
        return redirect(redirect_url)

    def form_invalid(self, form):
        is_ajax = self.request.headers.get("X-Requested-With") == "XMLHttpRequest" or self.request.headers.get("Accept") == "application/json"
        if is_ajax:
            errors = []
            for field, err_list in form.errors.items():
                for err in err_list:
                    prefix = f"{form.fields[field].label}: " if field in form.fields and form.fields[field].label else ""
                    errors.append(f"{prefix}{err}")
            return JsonResponse({"success": False, "errors": errors}, status=400)
        return super().form_invalid(form)


class OrderUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "orders/form.html"
    form_class = OrderForm
    model = Order

    def get_queryset(self):
        return Order.objects.select_related("responsible", "created_by").prefetch_related("items")

    def get_object(self, queryset=None):
        order = super().get_object(queryset)
        require_order_access(self.request.user, order)
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

    def _is_post_payment_locked(self, order: Order) -> bool:
        """Verifica se o pedido está bloqueado para edição pós-pagamento."""
        is_paid_stage = (
            order.stage in [
                Order.Stage.PAYMENT_CONFIRMED,
                Order.Stage.PRE_PRESS,
                Order.Stage.PRODUCTION,
                Order.Stage.READY,
                Order.Stage.DELIVERED,
            ]
            or order.payment_status == Order.PaymentStatus.PAID
            or bool(order.payment_confirmed_at)
        )
        if not is_paid_stage:
            return False

        user = self.request.user
        is_admin = (
            getattr(user, "is_admin", False)
            or getattr(user, "is_dev", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "role", "") == "administrador"
        )
        if is_admin:
            return False

        admin_pass = self.request.POST.get("admin_unlock_password", "").strip()
        admin_email = self.request.POST.get("admin_unlock_email", "").strip()
        if admin_pass:
            from django.contrib.auth import authenticate
            target_email = admin_email or user.email
            auth_user = authenticate(request=self.request, email=target_email, password=admin_pass)
            if auth_user and (
                getattr(auth_user, "is_admin", False)
                or getattr(auth_user, "is_dev", False)
                or getattr(auth_user, "is_superuser", False)
                or getattr(auth_user, "role", "") == "administrador"
            ):
                return False

        return True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["calculator_materials"] = material_catalogue()
        context["catalogue"] = full_catalogue()
        context["calculator_endpoint"] = reverse("orders:calculate_quote")
        is_locked = self._is_post_payment_locked(self.object)
        is_post_payment = (
            self.object.stage in [
                Order.Stage.PAYMENT_CONFIRMED,
                Order.Stage.PRE_PRESS,
                Order.Stage.PRODUCTION,
                Order.Stage.READY,
                Order.Stage.DELIVERED,
            ]
            or self.object.payment_status == Order.PaymentStatus.PAID
            or bool(self.object.payment_confirmed_at)
        )
        context["is_post_payment_locked"] = is_locked
        context["is_post_payment"] = is_post_payment

        existing_items = []
        if self.request.POST.get("calculation_payload"):
            try:
                posted_data = json.loads(self.request.POST.get("calculation_payload"))
                if isinstance(posted_data, dict) and "items" in posted_data:
                    existing_items = posted_data["items"]
                elif isinstance(posted_data, list):
                    existing_items = posted_data
            except Exception:
                pass
        if not existing_items and self.object and self.object.pk:
            existing_items = [
                item.calculation_snapshot or {
                    "kind": item.kind,
                    "material_code": item.material_code,
                    "material_name": item.material_name,
                    "product_color": item.product_color,
                    "product_size": item.product_size,
                    "art_width_cm": str(item.art_width_cm or ""),
                    "art_height_cm": str(item.art_height_cm or ""),
                    "quantity": item.art_quantity or int(item.billing_quantity),
                    "unit_price": str(item.unit_price),
                    "total": str(item.line_total),
                }
                for item in self.object.items.filter(kind__in=[OrderItem.Kind.MATERIAL, OrderItem.Kind.PRODUCT, OrderItem.Kind.SERVICE])
            ]
        context["existing_items"] = existing_items
        return context

    def form_valid(self, form):
        is_ajax = self.request.headers.get("X-Requested-With") == "XMLHttpRequest" or self.request.headers.get("Accept") == "application/json"
        if self._is_post_payment_locked(self.object):
            msg = "Edição bloqueada: este pedido já possui Pagamento Confirmado. Apenas administradores ou gerentes com autorização de senha podem alterar os dados."
            if is_ajax:
                return JsonResponse({"success": False, "errors": [msg]}, status=403)
            messages.error(self.request, msg)
            form.add_error(None, msg)
            return self.form_invalid(form)

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
            if is_ajax:
                return JsonResponse({"success": False, "errors": [exc.messages[0]]}, status=400)
            form.add_error(None, exc.messages[0])
            return self.form_invalid(form)

        messages.success(self.request, "Pedido atualizado.")
        redirect_url = reverse("production:detail", kwargs={"pk": self.object.pk})
        
        host = self.request.build_absolute_uri('/')[:-1]
        share_links = get_whatsapp_share_links(self.object, host=host)
        whatsapp_quote_url = share_links.get("quote_url") if share_links.get("phone") else ""

        if is_ajax:
            return JsonResponse({
                "success": True,
                "order_id": self.object.pk,
                "redirect_url": redirect_url,
                "whatsapp_share_url": whatsapp_quote_url,
            })

        return redirect(redirect_url)

    def form_invalid(self, form):
        is_ajax = self.request.headers.get("X-Requested-With") == "XMLHttpRequest" or self.request.headers.get("Accept") == "application/json"
        if is_ajax:
            errors = []
            for field, err_list in form.errors.items():
                for err in err_list:
                    prefix = f"{form.fields[field].label}: " if field in form.fields and form.fields[field].label else ""
                    errors.append(f"{prefix}{err}")
            return JsonResponse({"success": False, "errors": errors}, status=400)
        return super().form_invalid(form)


@login_required
@require_POST
def register_payment(request, pk: int):
    """Quick partial, multiple, or full payment registration for an order."""
    order = get_object_or_404(Order, pk=pk)
    require_order_access(request.user, order)
    from .forms import QuickPaymentForm
    from .models import OrderPayment
    from .services import _snapshot_receipt_on_payment
    form = QuickPaymentForm(request.POST)
    if form.is_valid():
        payments_payload = form.cleaned_data.get("payments_payload")
        payments_to_add = []

        if payments_payload:
            try:
                parsed = json.loads(payments_payload)
                if isinstance(parsed, list):
                    for p in parsed:
                        m = p.get("method")
                        raw_a = str(p.get("amount", "0")).strip().replace("R$", "").replace(" ", "")
                        if "," in raw_a:
                            raw_a = raw_a.replace(".", "").replace(",", ".")
                        amt = Decimal(raw_a)
                        if amt > Decimal("0.00") and m:
                            payments_to_add.append((m, amt, p.get("notes", "")))
            except Exception:
                pass

        if not payments_to_add and form.cleaned_data.get("paid_amount"):
            amt = form.cleaned_data["paid_amount"]
            m = form.cleaned_data.get("payment_method") or Order.PaymentMethod.PIX
            n = form.cleaned_data.get("notes") or ""
            payments_to_add.append((m, amt, n))

        if not payments_to_add:
            messages.error(request, "Informe ao menos uma forma de pagamento com valor maior que zero.")
            return redirect("production:detail", pk=pk)

        created_payments = []
        for m, amt, n in payments_to_add:
            op = OrderPayment.objects.create(
                order=order,
                payment_method=m,
                amount=amt,
                notes=n,
                recorded_by=request.user,
            )
            created_payments.append(op)

        total_added = sum((p[1] for p in payments_to_add), Decimal("0.00"))
        new_paid = (order.paid_amount or Decimal("0.00")) + total_added
        if new_paid > order.total_amount:
            new_paid = order.total_amount

        order.paid_amount = new_paid

        all_splits = list(order.payments.all())
        distinct_methods = set(sp.payment_method for sp in all_splits)
        if len(distinct_methods) > 1:
            order.payment_method = Order.PaymentMethod.MULTIPLE
        elif distinct_methods:
            order.payment_method = list(distinct_methods)[0]

        if order.paid_amount >= order.total_amount and order.total_amount > Decimal("0.00"):
            order.payment_status = Order.PaymentStatus.PAID
            order.payment_confirmed_at = timezone.now()
            order.payment_confirmed_by = request.user
            _snapshot_receipt_on_payment(order, request.user)
            if order.stage in {Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT}:
                order.stage = Order.Stage.PAYMENT_CONFIRMED
                order.stage_updated_at = timezone.now()
                OrderStageHistory.objects.create(order=order, previous_stage=Order.Stage.AWAITING_PAYMENT, new_stage=Order.Stage.PAYMENT_CONFIRMED, user=request.user)
        else:
            order.payment_status = Order.PaymentStatus.PARTIAL

        order.save()

        summary_parts = [f"R$ {amt:.2f} via {dict(Order.PaymentMethod.choices).get(m, m)}" for m, amt, _ in payments_to_add]
        desc = f"Pagamento(s) registrado(s): {', '.join(summary_parts)} (Total pago: R$ {order.paid_amount:.2f} de R$ {order.total_amount:.2f}).".strip()
        OrderHistory.objects.create(order=order, user=request.user, action="pagamento_registrado", description=desc)
        record_audit(request.user, "registro_pagamento", "pedido", order.pk, after={"adicionado": str(total_added), "total_pago": str(order.paid_amount), "status": order.payment_status}, request=request)
        messages.success(request, f"Pagamento de R$ {total_added:.2f} registrado com sucesso!")
    else:
        messages.error(request, "Erro ao registrar pagamento. Verifique o formulário.")

    return redirect("production:detail", pk=pk)


@login_required
@require_POST
def mark_order_as_paid(request, pk: int):
    """Ação rápida manual para alterar o status do pedido para Pedido Pago."""
    order = get_object_or_404(Order, pk=pk)
    require_order_access(request.user, order)
    from .services import _snapshot_receipt_on_payment

    payment_method = request.POST.get("payment_method") or order.payment_method or Order.PaymentMethod.PIX
    order.payment_method = payment_method
    order.paid_amount = order.total_amount
    order.payment_status = Order.PaymentStatus.PAID
    order.payment_confirmed_at = timezone.now()
    order.payment_confirmed_by = request.user
    _snapshot_receipt_on_payment(order, request.user)

    if order.stage in {Order.Stage.NEW, Order.Stage.AWAITING_PAYMENT}:
        previous_stage = order.stage
        order.stage = Order.Stage.PAYMENT_CONFIRMED
        order.stage_updated_at = timezone.now()
        OrderStageHistory.objects.create(
            order=order,
            previous_stage=previous_stage,
            new_stage=Order.Stage.PAYMENT_CONFIRMED,
            user=request.user,
        )

    order.save()
    desc = f"Status alterado manualmente para Pedido Pago (R$ {order.paid_amount:.2f} via {order.get_payment_method_display()})."
    OrderHistory.objects.create(order=order, user=request.user, action="pagamento_confirmado", description=desc)
    record_audit(
        request.user,
        "alterar_para_pago",
        "pedido",
        order.pk,
        after={"status": order.payment_status, "total_pago": str(order.paid_amount)},
        request=request,
    )
    messages.success(request, f"Pedido #{order.number} alterado para 'Pedido Pago' com sucesso!")
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("production:detail", pk=pk)


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


def download_primary_attachment(request, pk: int):
    """Direct fast download of an order's artwork attachment for Kanban and tables."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
    order = get_object_or_404(Order, pk=pk)
    require_order_access(request.user, order)
    attachment = order.attachments.filter(removed_at__isnull=True).order_by("pk").first()
    if not attachment or not attachment.file:
        messages.error(request, f"O pedido #{order.number} não possui arquivo de arte anexado.")
        return redirect("production:detail", pk=pk)
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
    """Return an authenticated, server-authoritative calculator result for DTF, shirts, or services."""
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

    kind = payload.get("kind") or payload.get("type")
    mat_code = str(payload.get("material_code") or payload.get("code") or "")

    cliente_id = payload.get("cliente_id") or payload.get("client_id")
    custom_price = payload.get("custom_price_per_meter") or payload.get("preco_especial_metro")
    if not custom_price and cliente_id:
        try:
            from apps.payments.models import Cliente
            cli = Cliente.objects.filter(pk=cliente_id).first()
            if cli and cli.preco_especial_metro:
                custom_price = cli.preco_especial_metro
        except Exception:
            pass

    try:
        if kind == "produto" or mat_code.startswith("camisa_"):
            shirt_code = str(payload.get("shirt_code") or mat_code)
            quote = calculate_shirt_quote(
                shirt_code=shirt_code,
                color=str(payload.get("color") or payload.get("product_color", "Preta")),
                size=str(payload.get("size") or payload.get("product_size", "M")),
                quantity=payload.get("quantity", 1),
            )
        elif kind == "servico" or mat_code in ("ajuste_preparacao_arquivo", "formato_halftone", "servico_avulso", "item_avulso", "avulso"):
            service_code = str(payload.get("service_code") or mat_code)
            custom_name = str(payload.get("name") or payload.get("material_name") or payload.get("custom_name") or "")
            custom_price = payload.get("unit_price") or payload.get("custom_price") or payload.get("price")
            quote = calculate_service_quote(
                service_code=service_code,
                quantity=payload.get("quantity", 1),
                custom_name=custom_name,
                custom_price=custom_price,
            )
        else:
            quote = calculate_quote(
                material_code=mat_code or "dtf_textil",
                width_cm=payload.get("width_cm"),
                height_cm=payload.get("height_cm"),
                quantity=payload.get("quantity"),
                custom_price_per_meter=custom_price,
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


@login_required
def grouped_invoice_view(request):
    """Visualização consolidada de 2 ou mais pedidos vinculados do mesmo cliente em fatura única."""
    order_ids_raw = request.GET.get("ids", "") or request.POST.get("ids", "")
    cliente_id = request.GET.get("cliente_id")
    
    order_ids = []
    if order_ids_raw:
        for val in order_ids_raw.split(","):
            val = val.strip()
            if val.isdigit():
                order_ids.append(int(val))

    if not order_ids and request.GET.getlist("order_id"):
        order_ids = [int(i) for i in request.GET.getlist("order_id") if i.isdigit()]

    if not order_ids and request.POST.getlist("order_id"):
        order_ids = [int(i) for i in request.POST.getlist("order_id") if i.isdigit()]

    if not order_ids:
        messages.error(request, "Selecione ao menos 2 pedidos para gerar a fatura agrupada.")
        if cliente_id:
            return redirect("payments:customer_detail", pk=cliente_id)
        return redirect("dashboard:index")

    orders = Order.objects.filter(id__in=order_ids).select_related("cliente", "responsible", "created_by").prefetch_related("items", "payments").order_by("created_at")
    if not orders.exists():
        messages.error(request, "Nenhum pedido encontrado com os IDs fornecidos.")
        return redirect("dashboard:index")

    first_order = orders.first()
    cliente = first_order.cliente
    client_name = cliente.nome if cliente else first_order.client_name
    client_phone = cliente.telefone if cliente else first_order.client_whatsapp

    total_amount = sum((o.total_amount for o in orders), Decimal("0.00"))
    total_paid = sum((o.paid_amount for o in orders), Decimal("0.00"))
    remaining_amount = max(Decimal("0.00"), total_amount - total_paid)
    total_meters = sum((o.total_meters for o in orders), Decimal("0.00"))

    all_items = []
    for o in orders:
        for it in o.items.all():
            all_items.append({
                "order_number": o.number,
                "order_pk": o.pk,
                "kind": it.kind,
                "material_name": it.material_name,
                "product_color": it.product_color,
                "product_size": it.product_size,
                "quantity": it.art_quantity or it.billing_quantity,
                "unit": it.billing_unit,
                "unit_price": it.unit_price,
                "total": it.line_total,
                "detail": it.calculation_detail or it.pricing_rule,
            })

    all_payments = []
    for o in orders:
        for p in o.payments.all():
            all_payments.append(p)

    invoice_number = f"FAT-{timezone.localdate().strftime('%Y%m%d')}-{cliente.id if cliente else first_order.id}"

    context = {
        "invoice_number": invoice_number,
        "date_issued": timezone.now(),
        "cliente": cliente,
        "client_name": client_name,
        "client_phone": client_phone,
        "orders": orders,
        "orders_count": len(orders),
        "order_ids_str": ",".join(str(o.id) for o in orders),
        "all_items": all_items,
        "all_payments": all_payments,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "remaining_amount": remaining_amount,
        "total_meters": total_meters,
    }
    return render(request, "orders/grouped_invoice.html", context)
