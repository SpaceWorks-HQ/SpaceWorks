from contextlib import nullcontext
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.tenant_migration import import_finalization, object_promotion
from apps.tenant_migration.import_job_cleanup import (
    FINALIZATION_SWEEP_LEASE_NAME,
    FINALIZATION_SWEEP_LEASE_DURATION,
    resume_expired_finalizing_import_jobs,
)
from apps.tenant_migration.insertion_errors import ImportCompletionAuditError
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.services_import_job import run_import_job
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.object_helpers import (
    memory_objects,
    prepare_source_objects,
    remove_source_object_footprint,
    write_object_bundle,
)
from tests.tenant_migration.protocol_helpers import superadmin


pytestmark = pytest.mark.django_db(transaction=True)


class WorkerExit(BaseException):
    pass


def test_claim_crash_sweep_waits_for_lease_expiry_and_completes(
    memory_objects, monkeypatch
):
    with enabled_encryption():
        source_user = make_user("lease-retry")
        source = make_space("lease-retry")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            actor = superadmin("lease-retry")
            case.job.actor = actor
            case.job.save(update_fields=("actor", "updated_at"))
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            real_claim = object_promotion._claim_staged_object

            def claim_then_crash(row):
                real_claim(row)
                raise WorkerExit("simulated exit after durable claim")

            monkeypatch.setattr(
                object_promotion, "_claim_staged_object", claim_then_crash
            )
            with pytest.raises(WorkerExit, match="after durable claim"):
                materialize_tenant(case.root, case.job, case.carried)
            monkeypatch.setattr(object_promotion, "_claim_staged_object", real_claim)
            case.job.refresh_from_db()
            claimed = case.job.import_objects.get(claimed_at__isnull=False)
            assert case.job.status == TenantImportJob.Status.FINALIZING

            redelivery = run_import_job(case.job.pk, actor_id=actor.pk)
            assert redelivery.status == TenantImportJob.Status.FINALIZING
            sweep_at = timezone.now()
            assert resume_expired_finalizing_import_jobs(now=sweep_at) == 0
            claimed.claimed_at = (
                timezone.now()
                - object_promotion.PROMOTION_LEASE_DURATION
                - timedelta(seconds=1)
            )
            claimed.save(update_fields=("claimed_at", "updated_at"))

            assert resume_expired_finalizing_import_jobs(
                now=sweep_at
                + FINALIZATION_SWEEP_LEASE_DURATION
                + timedelta(seconds=1)
            ) == 1
            case.job.refresh_from_db()

            assert case.job.status == TenantImportJob.Status.COMPLETED
            assert set(case.job.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.VERIFIED
            }


def test_finalization_sweep_is_registered_in_both_schedulers():
    task = "apps.tenant_migration.tasks.resume_expired_finalizing_import_jobs_task"

    assert settings.CELERY_BEAT_SCHEDULE[
        "resume-expired-tenant-import-finalizations"
    ]["task"] == task
    assert (
        "resume-expired-tenant-import-finalizations",
        task,
        5,
    ) in SCHEDULED_TASKS
    assert FINALIZATION_SWEEP_LEASE_NAME != "resume-expired-tenant-import-finalizations"


def test_materialization_failure_annotates_inner_failed_status(monkeypatch):
    actor = superadmin("failure-detail")
    job = TenantImportJob.objects.create(
        source_archive_digest="f" * 64,
        status=TenantImportJob.Status.MATERIALIZING,
        archive_path="unused-in-test.age",
        expires_at=timezone.now() + timedelta(days=1),
    )

    monkeypatch.setattr(
        "apps.tenant_migration.import_staging.decrypted_archive",
        lambda _path: nullcontext((None, ())),
    )

    def fail_after_inner_status_change(*_args, **_kwargs):
        TenantImportJob.objects.filter(pk=job.pk).update(
            status=TenantImportJob.Status.FAILED
        )
        raise RuntimeError("injected materialization failure")

    monkeypatch.setattr(
        "apps.tenant_migration.materialization.materialize_tenant",
        fail_after_inner_status_change,
    )

    with pytest.raises(RuntimeError, match="injected materialization failure"):
        run_import_job(job.pk, actor_id=actor.pk)

    job.refresh_from_db()
    assert job.status == TenantImportJob.Status.FAILED
    assert job.failure_code == "materialization_failed"
    assert job.failure_detail == "injected materialization failure"


def test_completion_audit_failure_preserves_finalizing_job_and_objects(
    memory_objects, monkeypatch
):
    with enabled_encryption():
        source_user = make_user("completion-audit")
        source = make_space("completion-audit")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            real_record = import_finalization.audit.record

            def fail_completion(actor, action, **kwargs):
                if action == "tenant_migration.import_completed":
                    raise RuntimeError("injected completion audit failure")
                return real_record(actor, action, **kwargs)

            monkeypatch.setattr(import_finalization.audit, "record", fail_completion)
            with pytest.raises(ImportCompletionAuditError):
                materialize_tenant(case.root, case.job, case.carried)

            case.job.refresh_from_db()
            assert case.job.status == TenantImportJob.Status.FINALIZING
            assert not case.job.verification_report
            assert set(case.job.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.VERIFIED
            }
            assert memory_objects["private"]
            assert memory_objects["public_image"]

            monkeypatch.setattr(import_finalization.audit, "record", real_record)
            actor = superadmin("completion-audit")
            completed = run_import_job(case.job.pk, actor_id=actor.pk)

            assert completed.status == TenantImportJob.Status.COMPLETED
