from django.apps import AppConfig


class PaymentsRailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments_rail"
    label = "payments_rail"

    def ready(self):
        from apps.separability.tombstones import register_separable_app

        register_separable_app("payments_rail")
