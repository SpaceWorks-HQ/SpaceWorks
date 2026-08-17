from celery import Task
from django.apps import apps

from apps.tenant_migration.gate_locks import unscoped_writer_shared_session
from apps.tenant_migration.gate_policy import (
    TASK_EXEMPTIONS,
    TASK_INTERNAL_PARTICIPANTS,
    TASK_TENANT_RESOLVERS,
)
from apps.tenant_migration.gate_runtime import boundary_tenant_write


class TenantGateTask(Task):
    """Default Celery boundary: drain before closure and refuse after closure."""

    abstract = True

    def __call__(self, *args, **kwargs):
        if self.name in TASK_EXEMPTIONS:
            return super().__call__(*args, **kwargs)
        if self.name in TASK_INTERNAL_PARTICIPANTS:
            return super().__call__(*args, **kwargs)
        resolver = TASK_TENANT_RESOLVERS.get(self.name)
        if resolver is not None:
            makerspace_id = _resolve_makerspace_id(resolver, args, kwargs)
            if makerspace_id is None:
                return super().__call__(*args, **kwargs)
            with boundary_tenant_write(makerspace_id):
                return super().__call__(*args, **kwargs)
        with unscoped_writer_shared_session():
            return super().__call__(*args, **kwargs)


def _resolve_makerspace_id(resolver, args, kwargs):
    model_label, position, field = resolver
    object_id = args[position] if len(args) > position else kwargs.get("job_id")
    if object_id is None:
        object_id = kwargs.get("log_id")
    if object_id is None:
        return None
    return (
        apps.get_model(model_label)
        .objects.filter(pk=object_id)
        .values_list(field, flat=True)
        .first()
    )
