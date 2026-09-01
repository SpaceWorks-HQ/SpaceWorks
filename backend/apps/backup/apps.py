from django.apps import AppConfig


class BackupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backup"

    def ready(self):
        from apps.backup import checks, signals  # noqa: F401
