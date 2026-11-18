"""Concilia com o Pagar.me o que pode ter escapado do webhook.

- Links de pagamento ativos: busca o pedido Pagar.me pelo código do link; se pago, registra; se venceu, expira.
- Cobranças Stone pendentes (PIX/cartão) dos últimos dias: consulta o status e reconcilia com o pedido.

Uso: python manage.py conciliar_pagamentos [--dias 7] [--simular]
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments import links
from apps.payments.models import LinkPagamento, StonePagamento
from apps.payments.stone.services.payments import refresh_payment
from apps.payments.stone.services.stone import StoneAPIError, StoneService


class Command(BaseCommand):
    help = "Concilia links de pagamento e cobranças pendentes com o Pagar.me (consulta a API)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=7, help="Janela de cobranças pendentes a conferir (padrão: 7 dias).")
        parser.add_argument("--simular", action="store_true", help="Só mostra o que mudaria, sem gravar nada.")

    def handle(self, *args, dias: int, simular: bool, **options):
        service = StoneService()
        service.require_server_credentials()
        resumo: Counter[str] = Counter()
        desde = timezone.now() - timedelta(days=dias)

        for link in LinkPagamento.objects.select_related("order").filter(status=LinkPagamento.Status.ATIVO):
            try:
                resultado = links.conciliar_link(link, service=service, aplicar=not simular)
            except (StoneAPIError, links.LinkErro) as exc:
                resultado = "erro"
                self.stderr.write(f"Link {link.order_code}: {getattr(exc, 'user_message', exc)}")
            resumo[f"links_{resultado}"] += 1
            if resultado != "sem_alteracao":
                self.stdout.write(f"Link {link.order_code} (pedido #{link.order.number}): {resultado}")

        pendentes = StonePagamento.objects.filter(status=StonePagamento.Status.PENDING, created_at__gte=desde).exclude(stone_payment_id="")
        for pagamento in pendentes:
            if simular:
                resumo["cobrancas_conferir"] += 1
                continue
            try:
                atualizado = refresh_payment(pagamento, service=service)
            except StoneAPIError as exc:
                resumo["cobrancas_erro"] += 1
                self.stderr.write(f"Cobrança #{pagamento.pk}: {exc.user_message}")
                continue
            resumo[f"cobrancas_{atualizado.status}"] += 1
            if atualizado.status != StonePagamento.Status.PENDING:
                self.stdout.write(f"Cobrança #{pagamento.pk}: {atualizado.status}")

        prefixo = "[SIMULAÇÃO] " if simular else ""
        self.stdout.write(self.style.SUCCESS(prefixo + "Conciliação concluída: " + (", ".join(f"{k}={v}" for k, v in sorted(resumo.items())) or "nada a fazer")))
