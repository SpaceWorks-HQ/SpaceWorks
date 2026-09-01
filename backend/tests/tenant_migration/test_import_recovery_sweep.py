import time
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tenant_migration import (
    import_job_cleanup,
    object_import,
    object_promotion,
)
from apps.tenant_migration.import_job_cleanup import (
    resume_expired_finalizing_import_jobs,
)
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.promotion_lease import PromotionClaimHeartbeat
from apps.tenant_migration.services_import_job import run_import_job
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.object_helpers import (
    materialize_until_crash,
    memory_objects,
    prepare_source_objects,
    remove_source_object_footprint,
    write_object_bundle,
)
from tests.tenant_migration.protocol_helpers import superadmin


pytestmark = pytest.mark.django_db(transaction=True)


def test_live_promotion_heartbeat_keeps_finalization_out_of_sweep(monkeypatch):
    actor = superadmin("live-promotion-heartbeat")
    target = make_space("live-promotion-heartbeat")
    job = TenantImportJob.objects.create(
        actor=actor,
        target_makerspace=target,
        source_archive_digest="a" * 64,
        status=TenantImportJob.Status.FINALIZING,
        expires_at=timezone.now() + timedelta(days=1),
    )
    row = TenantImportObject.objects.create(
        job=job,
        bucket_kind=TenantImportObject.BucketKind.PRIVATE,
        source_key="source/slow.bin",
        staging_key="staging/slow.bin",
        target_key="target/slow.bin",
        size=1,
        sha256="b" * 64,
    )
    lease_duration = timedelta(milliseconds=300)
    monkeypatch.setattr(
        import_job_cleanup, "PROMOTION_LEASE_DURATION", lease_duration
    )
    original_claim = object_promotion._claim_staged_object(row)

    with PromotionClaimHeartbeat(
        row.pk, original_claim, lease_duration=lease_duration
    ):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            row.refresh_from_db()
            if (
                timezone.now() - original_claim > lease_duration
                and row.claimed_at > original_claim
            ):
                break
            time.sleep(0.01)
        else:
            pytest.fail("promotion heartbeat did not renew the claim")

        assert resume_expired_finalizing_import_jobs(now=timezone.now()) == 0


def test_superseded_worker_preserves_replacement_completed_import(
    memory_objects, monkeypatch, caplog
):
    with enabled_encryption():
        source_user = make_user("superseded-worker")
        source = make_space("superseded-worker")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            actor = superadmin("superseded-worker")
            case.job.actor = actor
            case.job.save(update_fields=("actor", "updated_at"))
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            materialize_until_crash(case, monkeypatch, claim_number=1)
            real_copy = object_import.object_storage.copy_from_staging

            class PausedHeartbeat:
                def __init__(self, _row_id, claimed_at, *, lease_duration):
                    self.claimed_at = claimed_at

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def copy_after_takeover(*_args):
                rows = list(case.job.import_objects.order_by("pk"))
                active_job = TenantImportJob.objects.select_related(
                    "target_makerspace"
                ).get(pk=case.job.pk)
                original_claim = rows[0].claimed_at
                TenantImportObject.objects.filter(pk=rows[0].pk).update(
                    claimed_at=original_claim
                    - object_promotion.PROMOTION_LEASE_DURATION
                    - timedelta(seconds=1)
                )
                for row in rows:
                    row.refresh_from_db()
                    replacement_claim = object_promotion._claim_staged_object(row)
                    real_copy(
                        row.staging_key,
                        row.bucket_kind,
                        row.target_key,
                        row.content_type,
                    )
                    object_promotion._mark_promoted_and_charge(
                        row.pk,
                        active_job.target_makerspace,
                        claimed_at=replacement_claim,
                    )
                    row.refresh_from_db()
                    object_promotion._verify_promoted_object(row)
                fresh_job = TenantImportJob.objects.get(pk=case.job.pk)
                TenantImportJob.objects.filter(pk=case.job.pk).update(
                    status=TenantImportJob.Status.COMPLETED,
                    verification_report=fresh_job.materialization_report,
                    terminal_at=timezone.now(),
                )

            monkeypatch.setattr(
                object_promotion, "PromotionClaimHeartbeat", PausedHeartbeat
            )
            monkeypatch.setattr(
                object_import.object_storage,
                "copy_from_staging",
                copy_after_takeover,
            )
            with caplog.at_level("WARNING"):
                completed = run_import_job(case.job.pk, actor_id=actor.pk)

            assert completed.status == TenantImportJob.Status.COMPLETED
            assert set(completed.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.VERIFIED
            }
            assert memory_objects["private"]
            assert memory_objects["public_image"]
            assert "tenant_import_promotion_claim_lost" in caplog.text


def test_finalization_sweep_isolates_candidate_failures(monkeypatch, caplog):
    actor = superadmin("recovery-batch")
    first = TenantImportJob.objects.create(
        actor=actor,
        source_archive_digest="c" * 64,
        status=TenantImportJob.Status.FINALIZING,
        expires_at=timezone.now() + timedelta(days=1),
    )
    second = TenantImportJob.objects.create(
        actor=actor,
        source_archive_digest="d" * 64,
        status=TenantImportJob.Status.FINALIZING,
        expires_at=timezone.now() + timedelta(days=1),
    )
    older = timezone.now() - timedelta(minutes=2)
    TenantImportJob.objects.filter(pk=first.pk).update(updated_at=older)
    calls = []

    def recover(job_id, _actor_id):
        calls.append(job_id)
        if job_id == str(first.pk):
            raise RuntimeError("persistent recovery failure")
        TenantImportJob.objects.filter(pk=job_id).update(
            status=TenantImportJob.Status.COMPLETED,
            terminal_at=timezone.now(),
        )

    monkeypatch.setattr(
        "apps.tenant_migration.tasks.run_import_job_task.delay", recover
    )
    with caplog.at_level("ERROR"):
        recovered = resume_expired_finalizing_import_jobs(now=timezone.now())

    second.refresh_from_db()
    assert recovered == 2
    assert calls == [str(first.pk), str(second.pk)]
    assert second.status == TenantImportJob.Status.COMPLETED
    assert "tenant_import_finalization_recovery_failed" in caplog.text
    assert caplog.records[-1].failure_count == 1
