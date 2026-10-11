"""Reuse a validated HTTP/task boundary without acquiring a second lock connection."""
from contextlib import contextmanager

from django.db import transaction

from apps.tenant_migration.gate_runtime import (
    _boundary_shared_locks, boundary_tenant_write, tenant_write,
)


@contextmanager
def subject_boundary(makerspace_id):
    if makerspace_id in _boundary_shared_locks.get():
        yield
    else:
        with boundary_tenant_write(makerspace_id):
            yield


@contextmanager
def subject_write(makerspace_id):
    if makerspace_id in _boundary_shared_locks.get():
        with transaction.atomic():
            yield
    else:
        with tenant_write(makerspace_id):
            yield
