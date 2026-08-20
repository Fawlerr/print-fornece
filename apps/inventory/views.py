from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.accounts.permissions import AdministratorRequiredMixin
from .forms import SupplyItemForm, SupplyMovementForm
from .models import SupplyItem, SupplyMovement


class SupplyListView(LoginRequiredMixin, ListView):
    model = SupplyItem
    template_name = "inventory/list.html"
    context_object_name = "items"

    def get_queryset(self):
        qs = SupplyItem.objects.all()
        category = self.request.GET.get("category")
        search = self.request.GET.get("search")

        if category:
            qs = qs.filter(category=category)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(notes__icontains=search))

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_items = list(SupplyItem.objects.all())

        context["total_count"] = len(all_items)
        context["textil_count"] = sum(1 for i in all_items if i.category == SupplyItem.Category.DTF_TEXTIL)
        context["uv_count"] = sum(1 for i in all_items if i.category == SupplyItem.Category.DTF_UV)
        context["shirts_count"] = sum(1 for i in all_items if i.category == SupplyItem.Category.SHIRTS)
        context["low_stock_count"] = sum(1 for i in all_items if i.is_low_stock)
        
        context["current_category"] = self.request.GET.get("category", "")
        context["search_query"] = self.request.GET.get("search", "")
        context["categories"] = SupplyItem.Category.choices
        context["recent_movements"] = SupplyMovement.objects.select_related("item", "user")[:15]
        context["movement_form"] = SupplyMovementForm()
        return context


class SupplyCreateView(LoginRequiredMixin, AdministratorRequiredMixin, CreateView):
    model = SupplyItem
    form_class = SupplyItemForm
    template_name = "inventory/form.html"
    success_url = reverse_lazy("inventory:list")

    def form_valid(self, form):
        with transaction.atomic():
            item = form.save()
            if item.quantity > Decimal("0.00"):
                SupplyMovement.objects.create(
                    item=item,
                    movement_type=SupplyMovement.MovementType.ENTRY,
                    quantity=item.quantity,
                    previous_quantity=Decimal("0.00"),
                    new_quantity=item.quantity,
                    description="Saldo inicial no cadastro",
                    user=self.request.user,
                )
        messages.success(self.request, f"Insumo '{item.name}' cadastrado com sucesso!")
        return redirect(self.success_url)


class SupplyUpdateView(LoginRequiredMixin, AdministratorRequiredMixin, UpdateView):
    model = SupplyItem
    form_class = SupplyItemForm
    template_name = "inventory/form.html"
    success_url = reverse_lazy("inventory:list")

    def form_valid(self, form):
        messages.success(self.request, f"Insumo '{self.object.name}' atualizado com sucesso!")
        return super().form_valid(form)


class SupplyQuickMovementView(LoginRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        item = get_object_or_404(SupplyItem, pk=pk)
        form = SupplyMovementForm(request.POST)

        if form.is_valid():
            mov_type = form.cleaned_data["movement_type"]
            qty = form.cleaned_data["quantity"]
            desc = form.cleaned_data.get("description", "")

            with transaction.atomic():
                item = SupplyItem.objects.select_for_update().get(pk=item.pk)
                prev_qty = item.quantity

                if mov_type == SupplyMovement.MovementType.ENTRY:
                    new_qty = prev_qty + qty
                elif mov_type == SupplyMovement.MovementType.OUTPUT:
                    new_qty = max(Decimal("0.00"), prev_qty - qty)
                else:  # ADJUSTMENT
                    new_qty = qty

                item.quantity = new_qty
                item.save(update_fields=["quantity", "updated_at"])

                SupplyMovement.objects.create(
                    item=item,
                    movement_type=mov_type,
                    quantity=qty,
                    previous_quantity=prev_qty,
                    new_quantity=new_qty,
                    description=desc or "Ajuste manual de estoque",
                    user=request.user,
                )

            messages.success(
                request,
                f"Estoque de '{item.name}' atualizado: {prev_qty} -> {new_qty} {item.get_unit_display()}.",
            )
        else:
            messages.error(request, "Não foi possível registrar a movimentação. Verifique a quantidade.")

        return redirect("inventory:list")


class SupplyDeleteView(LoginRequiredMixin, AdministratorRequiredMixin, DeleteView):
    model = SupplyItem
    success_url = reverse_lazy("inventory:list")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        name = self.object.name
        self.object.delete()
        messages.success(request, f"Insumo '{name}' excluído do estoque.")
        return redirect(self.success_url)
