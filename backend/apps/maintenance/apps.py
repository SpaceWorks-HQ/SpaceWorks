from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.maintenance"

    def ready(self):
        from apps.separability.tombstones import register_separable_app

        register_separable_app("maintenance")
