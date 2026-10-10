from django.apps import AppConfig


class HardwareRequestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hardware_requests"
    label = "hardware_requests"

    def ready(self):
        from . import checks  # noqa: F401
