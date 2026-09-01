import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery(
    "config", task_cls="apps.tenant_migration.task_gate:TenantGateTask"
)
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
