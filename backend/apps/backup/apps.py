from django.apps import AppConfig


class BackupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backup"

    def ready(self):
        # Query-free and idempotent: ready() also runs for migrate, makemigrations, tests,
        # Celery workers and management commands.
        from apps.backup import signals  # noqa: F401

