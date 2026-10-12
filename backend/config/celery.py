import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery(
    "config", task_cls="apps.tenant_migration.task_gate:TenantGateTask"
)
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Registers the before_task_publish / task_prerun handlers that carry the request id
# from the web process into the worker. Import for its side effect; nothing to call.
import config.celery_signals  # noqa: E402,F401
