"""Structural Stone interface. Network calls remain deliberately disabled."""
from __future__ import annotations


class StoneIntegrationDisabled(RuntimeError):
    pass


class StonePaymentService:
    def create_pix_charge(self, order_id: int, amount):
        raise StoneIntegrationDisabled("Integração Stone ainda não ativada.")

    def create_card_checkout(self, order_id: int, amount):
        raise StoneIntegrationDisabled("Integração Stone ainda não ativada.")

    def get_payment_status(self, external_id: str):
        raise StoneIntegrationDisabled("Integração Stone ainda não ativada.")

    def process_webhook(self, payload: dict, headers: dict):
        raise StoneIntegrationDisabled("Webhook Stone desativado.")

