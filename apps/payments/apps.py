from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    verbose_name = "Cobranças"

    def ready(self):
        from . import signals  # noqa: F401  (desativa links de pagamento desatualizados)
