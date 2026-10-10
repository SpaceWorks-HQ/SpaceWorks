"""Coordinator: run against the isolated PostgreSQL runner; not executed in lane."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import ReplayCommand
from apps.hardware_requests.replay_cleanup import cleanup_replay_commands
from tests.hardware_requests.replay_helpers import envelope, prepare, replay_env
from tests.hardware_requests.recovery_helpers import (
    failed_issue, recovery_url, resolve, staff_client, successful_replacement,
)

pytestmark = pytest.mark.django_db


def test_acknowledgement_is_idempotent_and_preserves_attempt_domain_and_evidence(replay_env):
    env = replay_env
    row = failed_issue(env)
    original = ReplayCommand.objects.filter(pk=row.pk).values().get()
    photo = EvidencePhoto.objects.filter(pk=row.evidence_id).values().get()
    client = staff_client(env.user)
    first, again = resolve(client, row), resolve(client, row)
    assert first.status_code == again.status_code == 200
    assert first.data == again.data
    env.request.refresh_from_db()
    assert env.request.status == "accepted"
    row.refresh_from_db()
    after = ReplayCommand.objects.filter(pk=row.pk).values().get()
    for field, value in original.items():
        if field not in {"resolution_code", "resolved_by_id", "resolved_at", "replacement_command_id"}:
            assert after[field] == value
    assert EvidencePhoto.objects.filter(pk=row.evidence_id).values().get() == photo
    log = AuditLog.objects.get(action="kiosk.replay_resolved")
    assert log.actor == env.user and log.meta["replay_id"] == str(row.pk)
    assert first["Cache-Control"] == "private, no-store"


def test_successful_fresh_workflow_replacement_links_once_and_rejects_second_resolution(replay_env):
    env = replay_env
    row, second = failed_issue(env), failed_issue(env)
    replacement = successful_replacement(env)
    client = staff_client(env.user)
    response = resolve(client, row, "replaced_online", replacement)
    assert response.status_code == 200, response.data
    assert resolve(client, row, "replaced_online", replacement).status_code == 200
    assert resolve(client, row).status_code == 409
    assert resolve(client, second, "replaced_online", replacement).status_code == 409
    env.request.refresh_from_db()
    assert env.request.status == "issued"
    log = AuditLog.objects.get(action="kiosk.replay_resolved")
    assert log.meta["replacement_replay_id"] == str(replacement.pk)
    assert log.meta["subject_request_id"] == env.request.pk


@pytest.mark.parametrize("change", ["state", "kind", "subject", "aggregate", "age", "self"])
def test_incompatible_replacement_cannot_resolve_or_edit_failure(replay_env, change):
    env = replay_env
    row = failed_issue(env)
    replacement = successful_replacement(env)
    changes = {
        "state": {"state": "prepared", "completed_at": None},
        "kind": {"operation_kind": "reviewed_return"},
        "subject": {"subject_request_id": None},
        "aggregate": {"aggregate_id": row.aggregate_id, "sequence": row.sequence + 1},
        "age": {"created_at": row.completed_at - timedelta(seconds=1)},
    }
    if change == "self":
        replacement = row
    else:
        ReplayCommand.objects.filter(pk=replacement.pk).update(**changes[change])
    response = resolve(staff_client(env.user), row, "replaced_online", replacement)
    assert response.status_code == 409
    row.refresh_from_db()
    assert row.resolution_code is None and row.state == "failed"


def test_resolution_body_pair_and_database_constraints(replay_env):
    env = replay_env
    row = failed_issue(env)
    client = staff_client(env.user)
    assert resolve(client, row, "replaced_online").status_code == 400
    assert resolve(client, row, replacement=row).status_code == 400
    for values in (
        {"resolved_by": env.user},
        {"resolution_code": "acknowledged_no_change"},
        {"resolution_code": "other", "resolved_by": env.user, "resolved_at": timezone.now()},
        {"resolution_code": "replaced_online", "resolved_by": env.user, "resolved_at": timezone.now(), "replacement_command": row},
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            ReplayCommand.objects.filter(pk=row.pk).update(**values)
    assert resolve(client, row).status_code == 200
    row.refresh_from_db()
    row.failure_detail = "Edited historical failure"
    with pytest.raises(ValidationError, match="terminal"):
        row.save()
    row.refresh_from_db()
    row.resolved_at = timezone.now()
    with pytest.raises(ValidationError, match="review metadata"):
        row.save()


def test_only_failed_rows_are_recoverable_and_missing_replacement_is_safe(replay_env):
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    pending = ReplayCommand.objects.get()
    client = staff_client(env.user)
    assert client.get(recovery_url("detail", pk=pending.pk)).status_code == 404
    assert resolve(client, pending).status_code == 404
    row = failed_issue(env)
    response = client.post(recovery_url("resolve", pk=row.pk), {
        "resolution_code": "replaced_online", "replacement_command_id": str(uuid4()),
    }, format="json")
    assert response.status_code == 409


def test_cleanup_retains_replacement_until_failed_source_is_deleted(replay_env):
    env = replay_env
    row = failed_issue(env)
    replacement = successful_replacement(env)
    assert resolve(staff_client(env.user), row, "replaced_online", replacement).status_code == 200
    old = timezone.now() - timedelta(days=8)
    ReplayCommand.objects.filter(pk=replacement.pk).update(completed_at=old, expires_at=old)
    cleanup_replay_commands()
    assert ReplayCommand.objects.filter(pk=replacement.pk).exists()
    ReplayCommand.objects.filter(pk=row.pk).update(completed_at=old, expires_at=old)
    cleanup_replay_commands()
    assert not ReplayCommand.objects.filter(pk=row.pk).exists()
    cleanup_replay_commands()
    assert not ReplayCommand.objects.filter(pk=replacement.pk).exists()
    assert EvidencePhoto.objects.filter(pk=row.evidence_id).exists()


def test_resolution_obeys_closed_tenant_source_gate(replay_env):
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor
    env = replay_env
    row = failed_issue(env)
    close_gate(env.space, make_actor())
    assert resolve(staff_client(env.user), row).status_code == 423
    row.refresh_from_db()
    assert row.resolution_code is None
