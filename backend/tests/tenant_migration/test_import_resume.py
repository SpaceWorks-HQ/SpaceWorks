from unittest.mock import Mock

import pytest

from apps.audit.models import AuditLog
from apps.hardware_requests.models import HardwareRequest
from apps.tenant_migration import (
    cutover,
    import_finalization,
    object_import,
    object_promotion,
)
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.object_import import rollback_import_objects
from apps.tenant_migration.protocol_errors import TransitionConflictError
from apps.tenant_migration.services_import_job import run_import_job
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.object_helpers import (
    PRIVATE_BYTES,
    memory_objects,
    pairing_and_receipt,
    prepare_source_objects,
    remove_source_object_footprint,
    write_object_bundle,
)
from tests.tenant_migration.protocol_helpers import superadmin


pytestmark = pytest.mark.django_db(transaction=True)


class WorkerExit(BaseException):
    pass


def _crash_before_claim(monkeypatch, claim_number):
    real_claim = object_promotion._claim_staged_object
    calls = 0

    def claim(row):
        nonlocal calls
        calls += 1
        if calls == claim_number:
            raise WorkerExit("simulated worker exit")
        return real_claim(row)

    monkeypatch.setattr(object_promotion, "_claim_staged_object", claim)
    return real_claim


def _materialize_until_crash(case, monkeypatch, *, claim_number):
    real_claim = _crash_before_claim(monkeypatch, claim_number)
    with pytest.raises(WorkerExit, match="worker exit"):
        materialize_tenant(case.root, case.job, case.carried)
    monkeypatch.setattr(object_promotion, "_claim_staged_object", real_claim)
    case.job.refresh_from_db()
    assert case.job.status == TenantImportJob.Status.FINALIZING
    assert case.job.materialization_report
    assert not case.job.verification_report


def test_redelivery_resumes_partial_promotion_without_rematerializing(
    memory_objects, monkeypatch
):
    with enabled_encryption():
        source_user = make_user("resume-partial")
        source = make_space("resume-partial")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            _materialize_until_crash(case, monkeypatch, claim_number=2)

            states = list(case.job.import_objects.order_by("pk").values_list(
                "state", flat=True
            ))
            assert states == [
                TenantImportObject.State.VERIFIED,
                TenantImportObject.State.STAGED,
            ]
            actor = superadmin("resume-partial")
            materialize_again = Mock(side_effect=AssertionError("rematerialized"))
            monkeypatch.setattr(
                "apps.tenant_migration.materialization.materialize_tenant",
                materialize_again,
            )
            resumed = run_import_job(case.job.pk, actor_id=actor.pk)

            assert resumed.status == TenantImportJob.Status.COMPLETED
            assert resumed.verification_report == resumed.materialization_report
            assert set(resumed.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.VERIFIED
            }
            assert HardwareRequest.objects.filter(
                makerspace=resumed.target_makerspace
            ).count() == 1
            materialize_again.assert_not_called()


def test_redelivery_after_promotion_finishes_writes_report_once(
    memory_objects, monkeypatch
):
    with enabled_encryption():
        source_user = make_user("resume-report")
        source = make_space("resume-report")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            real_commit = import_finalization._commit_completion
            monkeypatch.setattr(
                import_finalization,
                "_commit_completion",
                Mock(side_effect=WorkerExit("report write crash")),
            )
            with pytest.raises(WorkerExit, match="report write crash"):
                materialize_tenant(case.root, case.job, case.carried)
            monkeypatch.setattr(import_finalization, "_commit_completion", real_commit)
            case.job.refresh_from_db()
            assert case.job.status == TenantImportJob.Status.FINALIZING
            assert not case.job.verification_report
            assert set(case.job.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.VERIFIED
            }

            actor = superadmin("resume-report")
            pairing, receipt = pairing_and_receipt(case.job, actor)
            with pytest.raises(TransitionConflictError, match="completed, verified"):
                cutover.activate_target(
                    pairing=pairing,
                    import_job=case.job,
                    receipt_envelope=receipt,
                    actor=actor,
                )
            first = run_import_job(case.job.pk, actor_id=actor.pk)
            second = run_import_job(case.job.pk, actor_id=actor.pk)

            assert first.status == second.status == TenantImportJob.Status.COMPLETED
            assert first.verification_report
            assert AuditLog.objects.filter(
                action="tenant_migration.import_completed",
                target_id=str(case.job.pk),
            ).count() == 1


def test_concurrent_redelivery_cannot_double_promote(memory_objects, monkeypatch):
    with enabled_encryption():
        source_user = make_user("resume-concurrent")
        source = make_space("resume-concurrent")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            _materialize_until_crash(case, monkeypatch, claim_number=1)
            actor = superadmin("resume-concurrent")
            real_copy = object_import.object_storage.copy_from_staging
            copies = []
            concurrent_states = []

            def copy_with_redelivery(*args):
                copies.append(args[2])
                if len(copies) == 1:
                    concurrent = run_import_job(case.job.pk, actor_id=actor.pk)
                    concurrent_states.append(concurrent.status)
                return real_copy(*args)

            monkeypatch.setattr(
                object_import.object_storage,
                "copy_from_staging",
                copy_with_redelivery,
            )
            completed = run_import_job(case.job.pk, actor_id=actor.pk)

            assert concurrent_states == [TenantImportJob.Status.FINALIZING]
            assert completed.status == TenantImportJob.Status.COMPLETED
            assert len(copies) == 2
            assert len(set(copies)) == 2


def test_rollback_from_partial_promotion_removes_all_objects_and_quota(
    memory_objects, monkeypatch
):
    with enabled_encryption():
        source_user = make_user("resume-rollback")
        source = make_space("resume-rollback")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            remove_source_object_footprint(case, memory_objects)
            _materialize_until_crash(case, monkeypatch, claim_number=2)

            assert rollback_import_objects(case.job) == 2
            assert not memory_objects["private"]
            assert not memory_objects["public_image"]
            assert memory_objects["quota"] == [
                ("add", len(PRIVATE_BYTES)),
                ("free", len(PRIVATE_BYTES)),
            ]
            assert set(case.job.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.ROLLED_BACK
            }
