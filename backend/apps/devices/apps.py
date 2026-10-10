from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.devices"
    label = "devices"

    def ready(self):
        # Query-free and idempotent, as every ready() must be. The checks and schema
        # extension register by import; the runtime manifest decides whether URLs/admin
        # ship. Retention (purge plan, export classification) is registered elsewhere and
        # stays live even when this app is tombstoned.
        from apps.devices import checks, openapi  # noqa: F401
        from apps.separability.tombstones import register_separable_app

        register_separable_app("devices")
