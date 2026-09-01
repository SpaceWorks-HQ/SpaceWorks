import uuid
from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.backup.models import BackupArchive, BackupRun, BackupRunCoverage
from apps.backup.runs import (
    BackupRunCoverageConflictError,
    BackupRunHolderMismatchError,
    EmptyBackupCohortError,
    finalize_run,
    open_run,
    record_coverage,
)
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


def _space(label, **overrides):
    return Makerspace.objects.create(
        name=label,
        slug=f"{label[:17]}-{uuid.uuid4().hex}",
        **overrides,
    )


def _archive(*, makerspace=None, covered_ids=(), run=None):
    completed_at = timezone.now()
    return BackupArchive.objects.create(
        scope=(
            BackupArchive.Scope.MAKERSPACE
            if makerspace
            else BackupArchive.Scope.DEPLOYMENT
        ),
        makerspace=makerspace,
        superadmin_access_at_decision=(
            makerspace.superadmin_access_enabled if makerspace else None
        ),
        backup_run=run,
        status=BackupArchive.Status.AVAILABLE,
        object_key=f"backup-runs/{uuid.uuid4()}.tar.age",
        manifest={
            "covered_makerspace_ids": list(covered_ids),
            "backup_run_id": str(run.pk) if run else None,
        },
        archive_sha256="a" * 64,
        completed_at=completed_at,
        expires_at=completed_at + timedelta(days=1),
    )


def _mark_covered(coverage, archive):
    BackupRunCoverage.objects.filter(pk=coverage.pk).update(
        state=BackupRunCoverage.State.COVERED,
        archive_sha256_snapshot=archive.archive_sha256,
        completed_at_snapshot=archive.completed_at,
    )


def test_finalize_fails_and_names_makerspace_without_counting_coverage():
    makerspace = _space("missing-proof")
    run = open_run()

    finalized = finalize_run(run)

    assert finalized.status == BackupRun.Status.FAILED
    assert str(makerspace.pk) in finalized.failure_detail
    assert "missing" in finalized.failure_detail


def test_open_run_refuses_an_empty_servable_cohort():
    with pytest.raises(EmptyBackupCohortError, match="zero servable makerspaces"):
        open_run()


def test_partial_unique_constraint_rejects_two_open_runs():
    _space("one-open-run")
    open_run()

    with pytest.raises(IntegrityError), transaction.atomic():
        open_run()


def test_finalize_refuses_a_nonmatching_holder():
    _space("holder-fence")
    run = open_run()
    run.holder = uuid.uuid4()

    with pytest.raises(BackupRunHolderMismatchError, match="holder does not match"):
        finalize_run(run)

    assert BackupRun.objects.get(pk=run.pk).status == BackupRun.Status.PENDING


def test_record_coverage_is_idempotent_but_rejects_a_different_archive():
    makerspace = _space("coverage-retry")
    run = open_run()
    first_archive = _archive(covered_ids=(makerspace.pk,))
    second_archive = _archive(covered_ids=(makerspace.pk,))

    first = record_coverage(
        run,
        makerspace=makerspace,
        archive=first_archive,
        path=BackupRunCoverage.Path.GLOBAL,
    )
    retried = record_coverage(
        run,
        makerspace=makerspace,
        archive=first_archive,
        path=BackupRunCoverage.Path.GLOBAL,
    )

    assert retried.pk == first.pk
    assert BackupRunCoverage.objects.filter(run=run).count() == 1
    with pytest.raises(BackupRunCoverageConflictError, match="different archive"):
        record_coverage(
            run,
            makerspace=makerspace,
            archive=second_archive,
            path=BackupRunCoverage.Path.GLOBAL,
        )


def test_coverage_path_that_contradicts_frozen_flag_does_not_count():
    makerspace = _space("wrong-path", superadmin_access_enabled=True)
    run = open_run()
    archive = _archive(makerspace=makerspace, covered_ids=(makerspace.pk,))
    coverage = record_coverage(
        run,
        makerspace=makerspace,
        archive=archive,
        path=BackupRunCoverage.Path.TENANT,
    )
    _mark_covered(coverage, archive)

    finalized = finalize_run(run)

    assert finalized.status == BackupRun.Status.FAILED
    assert str(makerspace.pk) in finalized.failure_detail
    assert "path" in finalized.failure_detail


@pytest.mark.parametrize("field", ["flag_snapshot", "cohort_at"])
def test_backup_run_trigger_freezes_cohort_fields(field):
    _space(f"run-freeze-{field}")
    run = open_run()
    value = {"different": False} if field == "flag_snapshot" else timezone.now()

    with pytest.raises(DatabaseError, match="immutable backup run"), transaction.atomic():
        BackupRun.objects.filter(pk=run.pk).update(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "makerspace_id_snapshot",
        "archive_id_snapshot",
        "archive_sha256_snapshot",
        "completed_at_snapshot",
        "run",
        "path",
        "archive",
        "makerspace",
        "state",
    ],
)
def test_backup_run_coverage_trigger_freezes_proof_and_binding(field):
    makerspace = _space(f"coverage-freeze-{field}")
    run = open_run()
    archive = _archive(covered_ids=(makerspace.pk,))
    coverage = BackupRunCoverage.objects.create(
        run=run,
        makerspace=makerspace,
        archive=archive,
        path=BackupRunCoverage.Path.GLOBAL,
        state=BackupRunCoverage.State.COVERED,
        makerspace_id_snapshot=makerspace.pk,
        archive_id_snapshot=archive.pk,
        archive_sha256_snapshot=archive.archive_sha256,
        completed_at_snapshot=archive.completed_at,
    )
    replacement_run = BackupRun.objects.create(
        cohort_at=timezone.now(),
        flag_snapshot={str(makerspace.pk): True},
        status=BackupRun.Status.COMPLETE,
        holder=uuid.uuid4(),
    )
    replacement_archive = _archive(covered_ids=(makerspace.pk,))
    replacement_makerspace = _space(f"coverage-replacement-{field}")
    updates = {
        "makerspace_id_snapshot": makerspace.pk + 1,
        "archive_id_snapshot": replacement_archive.pk,
        "archive_sha256_snapshot": "b" * 64,
        "completed_at_snapshot": timezone.now() + timedelta(seconds=1),
        "run": replacement_run,
        "path": BackupRunCoverage.Path.TENANT,
        "archive": replacement_archive,
        "makerspace": replacement_makerspace,
        "state": BackupRunCoverage.State.PENDING,
    }

    with pytest.raises(DatabaseError, match="backup run coverage"), transaction.atomic():
        BackupRunCoverage.objects.filter(pk=coverage.pk).update(**{field: updates[field]})


def test_makerspace_becoming_servable_after_cohort_is_for_the_next_run():
    cohort_makerspace = _space("cohort-member", superadmin_access_enabled=True)
    run = open_run()
    _space("late-member", superadmin_access_enabled=True)
    archive = _archive(covered_ids=(cohort_makerspace.pk,), run=run)
    coverage = record_coverage(
        run,
        makerspace=cohort_makerspace,
        archive=archive,
        path=BackupRunCoverage.Path.GLOBAL,
    )
    _mark_covered(coverage, archive)

    finalized = finalize_run(run)

    assert finalized.status == BackupRun.Status.COMPLETE
    assert finalized.failure_detail == ""
