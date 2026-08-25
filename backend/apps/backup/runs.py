import uuid
from collections import defaultdict

from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.utils import timezone

from apps.backup.models import BackupArchive, BackupRun, BackupRunCoverage
from apps.makerspaces.servability import servable_queryset


class BackupRunError(RuntimeError):
    pass


class EmptyBackupCohortError(BackupRunError):
    pass


class BackupRunHolderMismatchError(BackupRunError):
    pass


class BackupRunCoverageConflictError(BackupRunError):
    pass


@transaction.atomic
def open_run():
    cohort_at = timezone.now()
    cohort = list(
        servable_queryset()
        .order_by("id")
        .values_list("id", "superadmin_access_enabled")
    )
    if not cohort:
        raise EmptyBackupCohortError(
            "A backup run cannot open with zero servable makerspaces."
        )

    return BackupRun.objects.create(
        cohort_at=cohort_at,
        flag_snapshot={str(makerspace_id): enabled for makerspace_id, enabled in cohort},
        holder=uuid.uuid4(),
    )


@transaction.atomic
def record_coverage(run, *, makerspace, archive, path):
    locked_run = BackupRun.objects.select_for_update().get(pk=run.pk)
    _assert_holder(locked_run, run.holder)
    if locked_run.status not in (BackupRun.Status.PENDING, BackupRun.Status.RUNNING):
        raise BackupRunCoverageConflictError(
            "Coverage cannot be recorded against a terminal backup run."
        )
    if path not in BackupRunCoverage.Path.values:
        raise BackupRunCoverageConflictError(f"Unknown backup coverage path: {path!r}.")

    coverage, created = BackupRunCoverage.objects.get_or_create(
        run=locked_run,
        makerspace_id_snapshot=makerspace.pk,
        defaults={
            "makerspace": makerspace,
            "archive": archive,
            "path": path,
            "state": BackupRunCoverage.State.PENDING,
            "archive_id_snapshot": archive.pk,
        },
    )
    if not created and coverage.archive_id_snapshot != archive.pk:
        raise BackupRunCoverageConflictError(
            "A different archive is already bound to this run and makerspace."
        )
    if not created and (
        coverage.path != path
        or coverage.archive_id != archive.pk
        or coverage.makerspace_id not in (None, makerspace.pk)
    ):
        raise BackupRunCoverageConflictError(
            "Existing coverage does not match the requested immutable binding."
        )
    return coverage


@transaction.atomic
def finalize_run(run):
    locked_run = BackupRun.objects.select_for_update().get(pk=run.pk)
    _assert_holder(locked_run, run.holder)

    coverage_rows = list(
        BackupRunCoverage.objects.select_for_update()
        .filter(run=locked_run)
        .order_by("makerspace_id_snapshot", "pk")
    )
    archive_ids = {row.archive_id for row in coverage_rows if row.archive_id}
    # Keep this separate from the coverage query: archive is nullable, and Postgres
    # rejects FOR UPDATE across the outer join select_related() would produce.
    archives = {
        archive.pk: archive
        for archive in BackupArchive.objects.select_for_update().filter(pk__in=archive_ids)
    }

    failures = _coverage_failures(locked_run, coverage_rows, archives, timezone.now())
    locked_run.finished_at = timezone.now()
    if failures:
        locked_run.status = BackupRun.Status.FAILED
        locked_run.failure_detail = _failure_detail(failures)
    else:
        locked_run.status = BackupRun.Status.COMPLETE
        locked_run.failure_detail = ""
    locked_run.save(update_fields=("status", "failure_detail", "finished_at"))
    return locked_run


def _assert_holder(run, supplied_holder):
    if supplied_holder is None or run.holder != supplied_holder:
        raise BackupRunHolderMismatchError(
            "Backup run mutation refused because its holder does not match."
        )


def _coverage_failures(run, coverage_rows, archives, now):
    failures = defaultdict(list)
    try:
        flags = {int(key): value for key, value in run.flag_snapshot.items()}
        if any(type(value) is not bool for value in flags.values()):
            raise TypeError("flag values must be booleans")
    except (AttributeError, TypeError, ValueError):
        return {"snapshot": ["invalid_frozen_flag_snapshot"]}

    rows_by_makerspace = defaultdict(list)
    for row in coverage_rows:
        rows_by_makerspace[row.makerspace_id_snapshot].append(row)

    for makerspace_id in sorted(set(rows_by_makerspace) - set(flags)):
        failures[makerspace_id].append("outside_cohort")

    global_archive_ids = {
        rows_by_makerspace[makerspace_id][0].archive_id_snapshot
        for makerspace_id, enabled in flags.items()
        if enabled and len(rows_by_makerspace.get(makerspace_id, ())) == 1
    }
    if len(global_archive_ids) > 1:
        for makerspace_id, enabled in flags.items():
            if enabled:
                failures[makerspace_id].append("global_archive")

    for makerspace_id, enabled in sorted(flags.items()):
        rows = rows_by_makerspace.get(makerspace_id, ())
        if len(rows) != 1:
            failures[makerspace_id].append(
                "missing" if not rows else "duplicate"
            )
            continue
        row_errors = _coverage_row_errors(
            run, rows[0], archives.get(rows[0].archive_id), enabled, now
        )
        if row_errors:
            failures[makerspace_id].extend(row_errors)
    return dict(failures)


def _coverage_row_errors(run, coverage, archive, enabled, now):
    errors = []
    expected_path = (
        BackupRunCoverage.Path.GLOBAL if enabled else BackupRunCoverage.Path.TENANT
    )
    if coverage.path != expected_path:
        errors.append("path")
    if coverage.state != BackupRunCoverage.State.COVERED:
        errors.append("state")
    if archive is None:
        return errors + ["archive_missing"]
    if coverage.archive_id_snapshot != archive.pk:
        errors.append("archive_snapshot")
    if archive.status != BackupArchive.Status.AVAILABLE:
        errors.append("archive_status")
    if expected_path == BackupRunCoverage.Path.GLOBAL:
        if archive.scope != BackupArchive.Scope.DEPLOYMENT or archive.makerspace_id:
            errors.append("archive_scope")
    elif (
        archive.scope != BackupArchive.Scope.MAKERSPACE
        or archive.makerspace_id != coverage.makerspace_id_snapshot
    ):
        errors.append("archive_scope")

    manifest = archive.manifest if isinstance(archive.manifest, dict) else {}
    covered_ids = manifest.get("covered_makerspace_ids", [])
    if not isinstance(covered_ids, list):
        covered_ids = []
    if coverage.makerspace_id_snapshot not in covered_ids:
        errors.append("manifest_cohort")
    if (
        not coverage.archive_sha256_snapshot
        or coverage.archive_sha256_snapshot != archive.archive_sha256
    ):
        errors.append("archive_digest")
    if (
        coverage.completed_at_snapshot is None
        or coverage.completed_at_snapshot != archive.completed_at
    ):
        errors.append("archive_completed_at")
    if archive.expires_at is None or archive.expires_at <= now:
        errors.append("archive_expired")
    errors.extend(_archive_binding_errors(run, coverage, archive))
    return errors


def _archive_binding_errors(run, coverage, archive):
    """Activate archive-side run binding when the later K2 model fields land."""
    errors = []
    if _archive_has_field("backup_run"):
        if archive.backup_run_id != run.pk:
            errors.append("archive_run")
        manifest = archive.manifest if isinstance(archive.manifest, dict) else {}
        if manifest.get("backup_run_id") != str(run.pk):
            errors.append("manifest_run")
    if (
        coverage.path == BackupRunCoverage.Path.TENANT
        and _archive_has_field("makerspace_id_snapshot")
        and archive.makerspace_id_snapshot != coverage.makerspace_id_snapshot
    ):
        errors.append("archive_makerspace_snapshot")
    return errors


def _archive_has_field(name):
    try:
        BackupArchive._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return True


def _failure_detail(failures):
    entries = []
    for makerspace_id, reasons in failures.items():
        entries.append(f"{makerspace_id} ({','.join(reasons)})")
    detail = "Coverage validation failed for makerspace ids: " + "; ".join(entries)
    return detail[:500]
