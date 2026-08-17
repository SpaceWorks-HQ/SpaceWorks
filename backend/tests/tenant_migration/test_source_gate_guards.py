from pathlib import Path

import pytest

from apps.tenant_migration.source_gate_guards import (
    SourceGateCoverageError,
    validate_object_mutation_coverage,
    validate_http_coverage,
    validate_source_gate_coverage,
    validate_task_coverage,
)
from apps.tenant_migration.source_gate_http_guards import (
    validate_authenticated_http_boundary,
)


def _write(path, relative, content):
    target = Path(path) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_real_application_tree_has_total_source_gate_coverage():
    coverage = validate_source_gate_coverage()

    assert coverage["tasks"]
    assert coverage["webhooks"]
    assert coverage["http"]
    assert coverage["lifecycle"]
    assert coverage["objects"]


def test_task_guard_rejects_deliberate_nonparticipant(tmp_path):
    _write(
        tmp_path,
        "leak/tasks.py",
        "from celery import Task, shared_task\n"
        "@shared_task(base=Task)\n"
        "def escaped_task():\n"
        "    return None\n",
    )

    with pytest.raises(SourceGateCoverageError):
        validate_task_coverage(
            tmp_path, exemptions={}, resolvers={"apps.leak.tasks.escaped_task": ()},
            internal={},
        )


def test_task_guard_rejects_stale_exemption(tmp_path):
    with pytest.raises(SourceGateCoverageError, match="stale"):
        validate_task_coverage(
            tmp_path,
            exemptions={"apps.removed.tasks.old_task": "Removed task."},
            resolvers={},
            internal={},
        )


def test_object_guard_rejects_deliberate_nonparticipant(tmp_path):
    _write(
        tmp_path,
        "leak/service.py",
        "from apps.evidence import storage\n"
        "def escaped_delete(key):\n"
        "    storage.delete_object(key)\n",
    )

    with pytest.raises(SourceGateCoverageError, match="object mutations"):
        validate_object_mutation_coverage(tmp_path, participants={})


def test_object_guard_rejects_stale_participation(tmp_path):
    with pytest.raises(SourceGateCoverageError, match="stale"):
        validate_object_mutation_coverage(
            tmp_path,
            participants={"apps.removed.service.old_delete": "Removed call site."},
        )


def test_http_guard_rejects_deliberate_unscoped_anonymous_write(tmp_path):
    _write(
        tmp_path,
        "leak/views.py",
        "from rest_framework.permissions import AllowAny\n"
        "class EscapedView:\n"
        "    permission_classes = [AllowAny]\n"
        "    def post(self, request):\n"
        "        return mutate_tenant()\n",
    )

    with pytest.raises(SourceGateCoverageError, match="anonymous HTTP mutations"):
        validate_http_coverage(tmp_path, exemptions={}, participants={})


def test_http_guard_rejects_mutating_custom_authenticator(tmp_path):
    _write(
        tmp_path,
        "leak/views.py",
        "class EscapedView:\n"
        "    authentication_classes = [DifferentAuthentication]\n"
        "    def post(self, request):\n"
        "        return mutate_tenant()\n",
    )

    with pytest.raises(SourceGateCoverageError, match="overrides"):
        validate_authenticated_http_boundary(tmp_path, SourceGateCoverageError)
