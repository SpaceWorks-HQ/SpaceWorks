from django.apps import AppConfig


class DataExportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_export"

    def ready(self):
        from apps.data_export import signals  # noqa: F401
        from django.conf import settings
        from celery.schedules import crontab
        # Recovery scan for queued subject jobs, including broker-less deployments.
        settings.CELERY_BEAT_SCHEDULE["subject-access-exports"] = {
            "task": "apps.data_export.subject_tasks.sweep_subject_exports_task",
            "schedule": crontab(minute=15),
        }
