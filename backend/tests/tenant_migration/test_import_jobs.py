from datetime import timedelta

import pytest
from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.tenant_migration.models import ImportIdentityDecision, TenantImportJob
from apps.tenant_migration.services_import_job import (
    cleanup_expired_import_jobs,
    scrub_terminal_job,
)

pytestmark = pytest.mark.django_db(transaction=True)

DIGEST = "b" * 64


def make_job(**overrides):
    values = {
        "source_archive_digest": DIGEST,
        "source_makerspace_id": "41",
        "source_makerspace_slug": "source-lab",
        "source_makerspace_name": "Source Lab",
        "source_deployment_id": "source-deployment",
        "storage_mode": "included",
        "expires_at": timezone.now() + timedelta(days=1),
    }
    values.update(overrides)
    return TenantImportJob.objects.create(**values)


def make_decision(job, source_user_id, **overrides):
    values = {
        "job": job,
        "source_user_id": source_user_id,
        "source_email": f"{source_user_id}@source.test",
        "identity_resolution": ImportIdentityDecision.IdentityResolution.LINK_EXISTING,
        "membership_disposition": (
            ImportIdentityDecision.MembershipDisposition.IMPORT_MEMBERSHIP
        ),
    }
    values.update(overrides)
    return ImportIdentityDecision.objects.create(**values)


def test_job_precedes_the_tenant_and_never_protects_it():
    """The job is created before the tenant exists, and must never block its removal.

    A bare ``makerspace.delete()`` is not the behaviour under test and is not even
    reachable here: creating a makerspace seeds roles, categories and fence state that
    hold PROTECT references, which is exactly why ``lifecycle.purge()`` exists as an
    ordered graph that suspends immutability triggers. The behavioural half of this
    contract is covered by the purge test below; what is asserted here is the one thing
    a passing purge cannot show on its own -- that this FK is SET_NULL rather than
    PROTECT, since PROTECT would make purging an imported tenant impossible.
    """
    job = make_job()
    assert job.target_makerspace_id is None

    makerspace = Makerspace.objects.create(name="Imported Lab", slug="imported-lab")
    job.target_makerspace = makerspace
    job.save(update_fields=("target_makerspace", "updated_at"))
    job.refresh_from_db()
    assert job.target_makerspace_id == makerspace.pk

    field = TenantImportJob._meta.get_field("target_makerspace")
    assert field.null is True
    assert field.remote_field.on_delete is models.SET_NULL

    actor_field = TenantImportJob._meta.get_field("actor")
    assert actor_field.null is True
    assert actor_field.remote_field.on_delete is models.SET_NULL


def test_target_account_is_unique_per_job_but_null_targets_are_not():
    job = make_job()
    target = User.objects.create_user(username="target-account")
    make_decision(job, "source-1", target_user=target)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_decision(job, "source-2", target_user=target)

    make_decision(job, "source-3", target_user=None)
    make_decision(job, "source-4", target_user=None)
    assert job.identity_decisions.count() == 3


def test_identity_and_membership_axes_are_independent():
    job = make_job()

    decision = make_decision(
        job,
        "walk-in-no-membership",
        target_user=None,
        identity_resolution=ImportIdentityDecision.IdentityResolution.CREATE_WALK_IN,
        membership_disposition=(
            ImportIdentityDecision.MembershipDisposition.NO_MEMBERSHIP
        ),
    )

    assert decision.identity_resolution == "create_walk_in"
    assert decision.membership_disposition == "no_membership"


def test_makerspace_purge_removes_materialized_job_and_decisions(monkeypatch):
    actor = User.objects.create_superuser(username="import-purge-admin", password="pw")
    makerspace = Makerspace.objects.create(name="Purge Import", slug="purge-import")
    job = make_job(target_makerspace=makerspace)
    decision = make_decision(job, "purged-source-user", target_user=actor)
    makerspace.archived_at = timezone.now()
    makerspace.archived_by = actor
    makerspace.save(update_fields=("archived_at", "archived_by"))
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    monkeypatch.setattr(lifecycle, "_delete_public_image_keys", lambda keys: None)

    lifecycle.purge(makerspace, actor)

    assert not TenantImportJob.objects.filter(pk=job.pk).exists()
    assert not ImportIdentityDecision.objects.filter(pk=decision.pk).exists()


def test_scrub_terminal_job_keeps_digest_and_aggregate_only():
    job = make_job(status=TenantImportJob.Status.COMPLETED)
    first = User.objects.create_user(username="linked-first")
    make_decision(job, "linked", target_user=first)
    make_decision(
        job,
        "walk-in",
        target_user=None,
        identity_resolution=ImportIdentityDecision.IdentityResolution.CREATE_WALK_IN,
        membership_disposition=(
            ImportIdentityDecision.MembershipDisposition.NO_MEMBERSHIP
        ),
    )

    scrubbed = scrub_terminal_job(job)

    assert scrubbed.source_archive_digest == DIGEST
    assert scrubbed.aggregate_outcome == {
        "decision_count": 2,
        "identity_resolution": {"link_existing": 1, "create_walk_in": 1},
        "membership_disposition": {"import_membership": 1, "no_membership": 1},
    }
    assert scrubbed.source_makerspace_id == ""
    assert scrubbed.source_makerspace_slug == ""
    assert scrubbed.source_makerspace_name == ""
    assert scrubbed.source_deployment_id == ""
    assert scrubbed.storage_mode == ""
    assert scrubbed.scrubbed_at is not None
    assert not ImportIdentityDecision.objects.filter(job=job).exists()

    assert scrub_terminal_job(scrubbed).aggregate_outcome == scrubbed.aggregate_outcome


def test_cleanup_removes_only_expired_pre_tenant_jobs_and_is_idempotent():
    now = timezone.now()
    expired = make_job(expires_at=now - timedelta(seconds=1))
    live = make_job(
        source_archive_digest="c" * 64,
        expires_at=now + timedelta(seconds=1),
    )
    makerspace = Makerspace.objects.create(name="Materialized", slug="materialized")
    materialized = make_job(
        source_archive_digest="d" * 64,
        target_makerspace=makerspace,
        expires_at=now - timedelta(seconds=1),
    )
    make_decision(expired, "expired-person")

    assert cleanup_expired_import_jobs(now=now) == 1
    assert cleanup_expired_import_jobs(now=now) == 0
    assert not TenantImportJob.objects.filter(pk=expired.pk).exists()
    assert TenantImportJob.objects.filter(pk=live.pk).exists()
    assert TenantImportJob.objects.filter(pk=materialized.pk).exists()


def test_cleanup_unlinks_deleted_and_terminal_target_archives_after_commit(tmp_path):
    now = timezone.now()
    paths = [tmp_path / name for name in ("pending.age", "completed.age", "failed.age")]
    for path in paths:
        path.write_bytes(b"encrypted")
    pending = make_job(expires_at=now - timedelta(seconds=1), archive_path=str(paths[0]))
    completed_target = Makerspace.objects.create(name="Completed Target", slug="completed-target")
    completed = make_job(
        source_archive_digest="c" * 64, target_makerspace=completed_target,
        status=TenantImportJob.Status.COMPLETED,
        expires_at=now - timedelta(seconds=1), archive_path=str(paths[1]),
    )
    failed_target = Makerspace.objects.create(name="Failed Target", slug="failed-target")
    failed = make_job(
        source_archive_digest="d" * 64, target_makerspace=failed_target,
        status=TenantImportJob.Status.FAILED,
        expires_at=now - timedelta(seconds=1), archive_path=str(paths[2]),
    )

    assert cleanup_expired_import_jobs(now=now) == 3

    assert not TenantImportJob.objects.filter(pk=pending.pk).exists()
    completed.refresh_from_db()
    failed.refresh_from_db()
    assert completed.archive_path == ""
    assert failed.archive_path == ""
    assert not any(path.exists() for path in paths)


def test_import_archive_unlink_failure_is_logged_and_cannot_rollback_delete(
    tmp_path, monkeypatch, caplog,
):
    path = tmp_path / "undeletable.age"
    path.write_bytes(b"encrypted")
    job = make_job(archive_path=str(path))

    def fail_unlink(*_args, **_kwargs):
        raise OSError("injected unlink failure")

    monkeypatch.setattr("apps.tenant_migration.archive_retention.Path.unlink", fail_unlink)
    with caplog.at_level("ERROR"):
        with transaction.atomic():
            job.delete()
            assert path.exists()

    assert not TenantImportJob.objects.filter(pk=job.pk).exists()
    assert path.exists()
    assert "tenant_import_archive_unlink_failed" in caplog.text


def test_cleanup_task_is_registered_in_both_schedulers():
    task = "apps.tenant_migration.tasks.cleanup_expired_import_jobs_task"

    assert settings.CELERY_BEAT_SCHEDULE["cleanup-expired-tenant-import-jobs"][
        "task"
    ] == task
    assert ("cleanup-expired-tenant-import-jobs", task, 60) in SCHEDULED_TASKS
