from django.apps import AppConfig


class EvidenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.evidence"

    def ready(self):
        from apps.evidence import checks  # noqa: F401
