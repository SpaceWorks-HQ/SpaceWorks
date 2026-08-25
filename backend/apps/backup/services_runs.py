import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.backup.models import BackupArchive, BackupRun, BackupRunCoverage, PlatformBackupSettings
from apps.backup.operation_lock import deployment_operation_lock
from apps.backup.runs import finalize_run, open_run, record_coverage
from apps.backup.services_archives import (
    _run_archive_locked,
    create_archive,
    sweep_stale_promotions,
)
from apps.backup.services_lease import _claim_lease, _release_lease, _renew_lease
from apps.makerspaces.models import Makerspace


logger = logging.getLogger(__name__)


def schedule_deployment_backup():
    with deployment_operation_lock():
        sweep_stale_promotions()
        _fail_stale_runs()
        if not _claim_scheduled_window():
            return None
        try:
            run = open_run()
        except Exception as exc:
            logger.exception("scheduled_backup_run_open_failed")
            PlatformBackupSettings.objects.update_or_create(
                pk=1, defaults={"last_error": str(exc).strip()[:500]}
            )
            return None
        lease_claimed = False
        try:
            lease_claimed = _claim_lease(run.holder)
            if not lease_claimed:
                raise RuntimeError("Another backup already holds the deployment lease.")
            _start_run(run)
            _build_run_archives(run)
            run = _finalize_scheduled_run(run)
        except Exception as exc:
            logger.exception("scheduled_backup_run_failed", extra={"run_id": str(run.pk)})
            run = _fail_run(run, str(exc))
        finally:
            if lease_claimed:
                _release_lease(run.holder)
        return BackupRun.objects.get(pk=run.pk)


@transaction.atomic
def _claim_scheduled_window():
    row = PlatformBackupSettings.objects.select_for_update().filter(pk=1).first()
    if row is None:
        row = PlatformBackupSettings.objects.create(pk=1)
    now = timezone.now()
    if not row.automatic_backups_enabled:
        return False
    if row.last_scheduled_at and row.last_scheduled_at > now - timedelta(hours=20):
        return False
    row.last_scheduled_at = now
    row.save(update_fields=("last_scheduled_at", "updated_at"))
    return True


def _build_run_archives(run):
    frozen = {int(key): value for key, value in run.flag_snapshot.items()}
    makerspaces = {
        row.pk: row for row in Makerspace.objects.filter(pk__in=frozen).order_by("pk")
    }
    global_archive = create_archive(
        None,
        scope=BackupArchive.Scope.DEPLOYMENT,
        backup_run=run,
        superadmin_access_at_decision=True,
    )
    for makerspace_id, enabled in sorted(frozen.items()):
        if enabled:
            record_coverage(
                run,
                makerspace=makerspaces[makerspace_id],
                archive=global_archive,
                path=BackupRunCoverage.Path.GLOBAL,
            )
    _build_and_record(run, global_archive)

    for makerspace_id, enabled in sorted(frozen.items()):
        if enabled:
            continue
        makerspace = makerspaces[makerspace_id]
        archive = create_archive(
            None,
            scope=BackupArchive.Scope.MAKERSPACE,
            makerspace=makerspace,
            backup_run=run,
            superadmin_access_at_decision=enabled,
        )
        record_coverage(
            run,
            makerspace=makerspace,
            archive=archive,
            path=BackupRunCoverage.Path.TENANT,
        )
        _build_and_record(run, archive)


def _build_and_record(run, archive):
    if not _renew_lease(run.holder):
        raise RuntimeError("The backup run lost its deployment lease.")
    completed = _run_archive_locked(
        archive.pk, manage_lease=False, lease_holder=run.holder
    )
    if completed and completed.status == BackupArchive.Status.AVAILABLE:
        _mark_coverage_covered(run, completed)


@transaction.atomic
def _start_run(run):
    started = BackupRun.objects.filter(
        pk=run.pk,
        holder=run.holder,
        status=BackupRun.Status.PENDING,
    ).update(status=BackupRun.Status.RUNNING)
    if not started:
        raise RuntimeError("The backup run start fence was lost.")
    if not _renew_lease(run.holder):
        raise RuntimeError("The backup run lost its deployment lease.")


@transaction.atomic
def _mark_coverage_covered(run, archive):
    owned = BackupRun.objects.select_for_update().filter(
        pk=run.pk,
        holder=run.holder,
        status=BackupRun.Status.RUNNING,
    ).exists()
    if not owned or archive.backup_run_id != run.pk:
        raise RuntimeError("Coverage finalization refused because the run fence was lost.")
    BackupRunCoverage.objects.filter(
        run=run,
        archive=archive,
        state=BackupRunCoverage.State.PENDING,
    ).update(
        state=BackupRunCoverage.State.COVERED,
        archive_sha256_snapshot=archive.archive_sha256,
        completed_at_snapshot=archive.completed_at,
    )


@transaction.atomic
def _finalize_scheduled_run(run):
    finalized = finalize_run(run)
    if finalized.status == BackupRun.Status.COMPLETE:
        PlatformBackupSettings.objects.filter(pk=1).update(
            last_success_at=finalized.finished_at,
            last_error="",
        )
    return finalized


@transaction.atomic
def _fail_run(run, detail):
    message = str(detail).strip()[:500]
    filters = {
        "pk": run.pk,
        "holder": run.holder,
        "status__in": (BackupRun.Status.PENDING, BackupRun.Status.RUNNING),
    }
    BackupRun.objects.filter(**filters).update(
        status=BackupRun.Status.FAILED,
        failure_detail=message or "The scheduled backup run failed.",
        finished_at=timezone.now(),
    )
    return BackupRun.objects.get(pk=run.pk)


@transaction.atomic
def _fail_stale_runs():
    stale = list(
        BackupRun.objects.filter(
            status__in=(BackupRun.Status.PENDING, BackupRun.Status.RUNNING)
        ).values_list("pk", "status", "holder")
    )
    for run_id, status, holder in stale:
        holder_filter = {"holder": holder} if holder is not None else {"holder__isnull": True}
        failed = BackupRun.objects.filter(
            pk=run_id, status=status, **holder_filter
        ).update(
            status=BackupRun.Status.FAILED,
            failure_detail="The previous backup run exited without finalizing.",
            finished_at=timezone.now(),
        )
        if failed and holder is not None:
            _release_lease(holder)
