from django.apps import AppConfig


class DataExportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_export"

    def ready(self):
        from apps.data_export import signals  # noqa: F401
