"""Offsite integrity admission, retries, task isolation and per-tenant retention."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.backup import offsite_client, offsite_enqueue, offsite_push, tasks_offsite
from apps.backup.models import BackupArtifactLedger, BackupDestinationUpload
from apps.backup.offsite_retention import prune_offsite_copies
from apps.backup.offsite_reverify import REVERIFY_AFTER, reverify_offsite_copies
from apps.makerspaces.models import Makerspace
from tests.backup.offsite_test_support import (
    destination_bucket, make_destination, offsite_bucket, open_run, stored_archive,  # noqa: F401
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("state,size,digest,accepted", [
    ("available", 10, "a" * 64, True), ("pending", 10, "a" * 64, False),
    ("available", 11, "a" * 64, False), ("available", 10, "b" * 64, False),
])
def test_artifact_ledger_is_authoritative_and_disagreement_refuses_the_copy(monkeypatch, state, size, digest, accepted):
    archive = SimpleNamespace(pk=uuid.uuid4(), size_bytes=10, archive_sha256="a" * 64)
    ledger = SimpleNamespace(state=state, expected_size_bytes=size, outer_sha256=digest)
    monkeypatch.setattr(BackupArtifactLedger.objects, "filter",
                        lambda **kwargs: SimpleNamespace(first=lambda: ledger))
    if accepted:
        assert offsite_enqueue.expected_facts(archive) == (10, "a" * 64, "artifact_ledger")
    else:
        with pytest.raises(offsite_enqueue.OffsiteIntegrityError):
            offsite_enqueue.expected_facts(archive)


def test_one_destination_failure_does_not_prevent_another_from_verifying(offsite_bucket, monkeypatch):
    archive = stored_archive()
    bad = make_destination(offsite_bucket, name="a-broken")
    good = make_destination(destination_bucket(), name="b-good")
    real_client = offsite_client.destination_client

    def destination_client(destination):
        if destination.pk == bad.pk:
            raise offsite_client.OffsiteDestinationError("destination_down")
        return real_client(destination)

    monkeypatch.setattr(offsite_client, "destination_client", destination_client)
    assert offsite_enqueue.enqueue_offsite_uploads() == 2
    assert offsite_push.push_due_uploads() == 2
    assert BackupDestinationUpload.objects.get(destination=good).state == "bytes_verified"
    assert BackupDestinationUpload.objects.get(destination=bad).last_error_code == "destination_down"
    archive.refresh_from_db()
    assert archive.status == archive.Status.AVAILABLE


def test_expired_upload_claim_is_retried_and_previous_holder_cannot_commit(offsite_bucket):
    archive = stored_archive()
    make_destination(offsite_bucket)
    offsite_enqueue.enqueue_offsite_uploads()
    row = BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk)
    old_holder = uuid.uuid4()
    BackupDestinationUpload.objects.filter(pk=row.pk).update(
        state="uploading", holder=old_holder, claimed_until=timezone.now() - timedelta(seconds=1),
    )
    new_holder = offsite_push._claim(row.pk)
    assert new_holder is not None and new_holder != old_holder
    offsite_push._record_failure(row, old_holder, "stale_failure")
    offsite_push._record_verified(row, old_holder, row.expected_size_bytes, row.expected_sha256)
    row.refresh_from_db()
    assert row.holder == new_holder and row.state == "uploading"
    offsite_push._push_one(row.pk, new_holder)
    row.refresh_from_db()
    assert row.state == "bytes_verified" and row.holder is None


def test_retention_keeps_newest_deployment_and_each_tenant_on_every_destination(offsite_bucket):
    spaces = [Makerspace.objects.create(name=f"Retention {i}", slug=f"offsite-retention-{i}") for i in range(2)]
    run = open_run([space.pk for space in spaces])
    destinations = [make_destination(offsite_bucket), make_destination(destination_bucket())]
    newest_ids = set()
    for space in (None, *spaces):
        common = {"scope": "makerspace", "makerspace": space, "run": run} if space else {}
        stored_archive(completed_at=timezone.now() - timedelta(days=10), **common)
        newest_ids.add(stored_archive(completed_at=timezone.now() - timedelta(days=5), **common).pk)
    for destination in destinations:
        destination.retention_days = 1
        destination.save()
    assert offsite_enqueue.enqueue_offsite_uploads() == 12
    offsite_push.push_due_uploads(limit=20)

    assert prune_offsite_copies() == 6
    assert set(BackupDestinationUpload.objects.filter(state="bytes_verified").values_list(
        "archive_id_snapshot", flat=True,
    )) == newest_ids
    assert prune_offsite_copies() == 0


def test_retention_and_reverify_transport_failures_preserve_verified_facts(offsite_bucket, monkeypatch):
    old = stored_archive(completed_at=timezone.now() - timedelta(days=10))
    stored_archive(completed_at=timezone.now() - timedelta(days=5))
    make_destination(offsite_bucket, retention_days=1)
    offsite_enqueue.enqueue_offsite_uploads()
    offsite_push.push_due_uploads()
    previous = timezone.now() - REVERIFY_AFTER - timedelta(days=1)
    BackupDestinationUpload.objects.update(verified_at=previous)

    def unavailable(*args, **kwargs):
        raise offsite_client.OffsiteDestinationError("transport_failed")

    monkeypatch.setattr(offsite_client, "destination_client", unavailable)
    assert prune_offsite_copies() == 0
    assert reverify_offsite_copies() == 0
    row = BackupDestinationUpload.objects.get(archive_id_snapshot=old.pk)
    assert row.state == "bytes_verified" and row.verified_at == previous
    assert row.verified_sha256 == row.expected_sha256
    assert row.last_error_code == "transport_failed"


def test_offsite_task_continues_after_a_step_failure_and_dispatch_is_fail_safe(monkeypatch):
    calls = []

    def broken():
        raise RuntimeError("destination unavailable")

    monkeypatch.setattr(offsite_push, "enqueue_offsite_uploads", broken)
    monkeypatch.setattr(offsite_push, "push_due_uploads", lambda: calls.append("push") or 2)
    monkeypatch.setattr("apps.backup.offsite_retention.prune_offsite_copies", lambda: 3)
    monkeypatch.setattr("apps.backup.offsite_reverify.reverify_offsite_copies", lambda: 4)
    assert tasks_offsite.push_offsite_backups_task() == {"enqueued": 0, "pushed": 2, "pruned": 3, "reverified": 4}
    assert calls == ["push"]
    monkeypatch.setattr(tasks_offsite.push_offsite_backups_task, "delay", broken)
    assert tasks_offsite.dispatch_offsite_push() is False
