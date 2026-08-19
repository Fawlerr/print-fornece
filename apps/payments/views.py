from __future__ import annotations

from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.audit.services import record_audit
from apps.orders.models import Order
from apps.orders.services import validate_upload
from .forms import AdicionarCreditoForm, ClienteArquivoForm, ClienteForm
from .models import Cliente, ClienteArquivo


class ClienteListView(LoginRequiredMixin, ListView):
    model = Cliente
    template_name = "payments/customer_list.html"
    context_object_name = "clientes"
    paginate_by = 25

    def get_queryset(self):
        queryset = Cliente.objects.annotate(
            pedidos_count=Count("pedidos_vinculados", distinct=True),
            arquivos_count=Count("arquivos_registrados", distinct=True),
        )
        search = self.request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(nome__icontains=search) | Q(telefone__icontains=search) | Q(cpf_cnpj__icontains=search) | Q(email__icontains=search)
            )
        return queryset.order_by("nome")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_term"] = self.request.GET.get("search", "")
        return context


class ClienteCreateView(LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "payments/customer_form.html"

    def form_valid(self, form):
        cliente = form.save()
        record_audit(self.request.user, "criacao_cliente", "cliente", cliente.pk, after={"nome": cliente.nome}, request=self.request)
        messages.success(self.request, f"Cliente {cliente.nome} cadastrado com sucesso.")
        return redirect("payments:customer_detail", pk=cliente.pk)


class ClienteUpdateView(LoginRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "payments/customer_form.html"

    def form_valid(self, form):
        cliente = form.save()
        record_audit(self.request.user, "edicao_cliente", "cliente", cliente.pk, after={"nome": cliente.nome}, request=self.request)
        messages.success(self.request, f"Dados do cliente {cliente.nome} atualizados com sucesso.")
        return redirect("payments:customer_detail", pk=cliente.pk)


class ClienteDetailView(LoginRequiredMixin, DetailView):
    model = Cliente
    template_name = "payments/customer_detail.html"
    context_object_name = "cliente"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente = self.object
        context["arquivo_form"] = ClienteArquivoForm()
        context["credito_form"] = AdicionarCreditoForm()
        context["arquivos_registrados"] = cliente.arquivos_registrados.all().order_by("-created_at")
        
        # Histórico de pedidos do cliente (por vínculo direto ou nome)
        context["pedidos"] = Order.objects.filter(
            Q(cliente=cliente) | Q(client_name__iexact=cliente.nome) | Q(client_whatsapp=cliente.telefone)
        ).distinct().order_by("-created_at")[:20]
        
        return context


class ClienteDeleteView(LoginRequiredMixin, DeleteView):
    model = Cliente
    template_name = "payments/customer_confirm_delete.html"
    success_url = reverse_lazy("payments:customer_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente = self.object
        context["arquivos_count"] = cliente.arquivos_registrados.count()
        context["pedidos_count"] = cliente.pedidos_vinculados.count()
        return context

    def form_valid(self, form):
        cliente = self.get_object()
        nome = cliente.nome
        arquivos_count = cliente.arquivos_registrados.count()
        saldo = str(cliente.saldo_credito)
        record_audit(
            self.request.user,
            "exclusao_cliente",
            "cliente",
            cliente.pk,
            before={"nome": nome, "arquivos_deletados": arquivos_count, "saldo_perdido": saldo},
            request=self.request,
        )
        messages.warning(self.request, f"Cliente {nome} e seus {arquivos_count} arquivo(s) foram excluídos permanentemente.")
        return super().form_valid(form)


@login_required
@require_POST
def cliente_add_arquivo(request, pk: int):
    cliente = get_object_or_404(Cliente, pk=pk)
    files = request.FILES.getlist("arquivo")
    nome_descricao = request.POST.get("nome", "").strip()

    if not files:
        messages.error(request, "Selecione ao menos um arquivo para anexar ao cliente.")
        return redirect("payments:customer_detail", pk=pk)

    count = 0
    for upload in files:
        try:
            original_name, content_type = validate_upload(upload)
            arquivo_obj = ClienteArquivo(
                cliente=cliente,
                nome=nome_descricao or original_name,
                content_type=content_type,
                tamanho=upload.size,
            )
            arquivo_obj.arquivo.save(original_name, upload, save=True)
            count += 1
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect("payments:customer_detail", pk=pk)

    record_audit(request.user, "adicionou_arquivo_cliente", "cliente", cliente.pk, after={"quantidade": count}, request=request)
    messages.success(request, f"{count} arquivo(s) registrado(s) com sucesso para o cliente {cliente.nome}.")
    return redirect("payments:customer_detail", pk=pk)


@login_required
@require_POST
def cliente_add_credito(request, pk: int):
    cliente = get_object_or_404(Cliente, pk=pk)
    form = AdicionarCreditoForm(request.POST)
    if form.is_valid():
        valor = form.cleaned_data["valor_credito"]
        metros = form.cleaned_data["metros_adicionar"]

        cliente.saldo_credito = (cliente.saldo_credito or Decimal("0.00")) + valor
        cliente.metros_saldo = (cliente.metros_saldo or Decimal("0.00")) + metros
        # Se for plano de volume padrão, define também preço especial padrão caso não exista
        if not cliente.preco_especial_metro or cliente.preco_especial_metro > Decimal("35.00"):
            cliente.preco_especial_metro = Decimal("35.00")
        cliente.save(update_fields=["saldo_credito", "metros_saldo", "preco_especial_metro", "updated_at"])

        record_audit(
            request.user,
            "adicionou_credito_volume",
            "cliente",
            cliente.pk,
            after={"valor_adicionado": str(valor), "metros_adicionados": str(metros), "saldo_total": str(cliente.saldo_credito)},
            request=request,
        )
        messages.success(request, f"Recarga aplicada! Saldo atual: R$ {cliente.saldo_credito:.2f} ({cliente.metros_saldo:.1f} metros).")
    else:
        messages.error(request, "Dados de recarga inválidos. Verifique os valores.")

    return redirect("payments:customer_detail", pk=pk)


@login_required
def api_clientes_search(request):
    term = request.GET.get("q", "").strip()
    if len(term) < 2:
        return JsonResponse({"results": []})

    clientes = Cliente.objects.filter(
        Q(nome__icontains=term) | Q(telefone__icontains=term) | Q(cpf_cnpj__icontains=term)
    ).order_by("nome")[:15]

    data = [
        {
            "id": c.pk,
            "nome": c.nome,
            "telefone": c.telefone or "",
            "preco_especial_metro": str(c.preco_especial_metro) if c.preco_especial_metro else "",
            "saldo_credito": str(c.saldo_credito or "0.00"),
            "metros_saldo": str(c.metros_saldo or "0.00"),
        }
        for c in clientes
    ]
    return JsonResponse({"results": data})


@csrf_exempt
def stone_webhook(request):
    """Reserved endpoint; it cannot alter an order or confirm payment."""
    return JsonResponse({"error": "Integração Stone ainda não habilitada."}, status=503)
