from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from .forms import OrderForm
from .models import Order, OrderAttachment
from .services import create_order, require_order_access, update_order


class OrderCreateView(LoginRequiredMixin, CreateView):
    template_name = "orders/form.html"
    form_class = OrderForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            self.object = create_order(form=form, actor=self.request.user, files=self.request.FILES.getlist("attachments"), request=self.request)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
            return self.form_invalid(form)
        messages.success(self.request, f"Pedido {self.object.number} criado com sucesso.")
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
        return order

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            self.object = update_order(order=self.object, form=form, actor=self.request.user, files=self.request.FILES.getlist("attachments"), request=self.request)
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
