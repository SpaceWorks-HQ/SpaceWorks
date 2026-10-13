"""Safe deployment summaries: no provider errors, secrets or tenant snapshots."""

from django.db.models import Q
from django.utils import timezone

from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.operations.models_scheduling import PeriodicTaskRun


def scheduler_snapshot(now=None):
    now = now or timezone.now()
    runs = {row.name: row for row in PeriodicTaskRun.objects.all()}
    results = []
    for name, path, cadence in SCHEDULED_TASKS:
        row = runs.get(name)
        last_run = row.last_run_at if row else None
        age = (now - last_run).total_seconds() if last_run else None
        state = "ok"
        if row and row.last_error:
            state = "error"
        elif age is None or age > cadence * 60 * 3:
            state = "warn"
        results.append({
            "name": name, "task": path, "cadence_minutes": cadence,
            "last_run_at": last_run, "status": state,
        })
    return results


def backup_snapshot():
    from apps.backup.models import PlatformBackupSettings
    from apps.backup.models_runs import BackupRun

    config = PlatformBackupSettings.objects.filter(pk=1).first()
    run = BackupRun.objects.order_by("-started_at").first()
    return {
        "automatic_enabled": bool(config and config.automatic_backups_enabled),
        "last_success_at": config.last_success_at if config else None,
        "status": run.status if run else "never",
        "started_at": run.started_at if run else None,
        "finished_at": run.finished_at if run else None,
        "has_error": bool(config and config.last_error),
        "cadence_minutes": next(c for n, _, c in SCHEDULED_TASKS
                                if n == "scheduled-deployment-backup"),
    }


def offsite_snapshot(visible_ids):
    from apps.audit.models import AuditLog
    from apps.backup.models_offsite import BackupDestination, BackupDestinationUpload

    results = []
    uploads = BackupDestinationUpload.objects.filter(
        Q(scope_snapshot="deployment", makerspace_id_snapshot__isnull=True)
        | Q(scope_snapshot="makerspace", makerspace_id_snapshot__in=visible_ids),
    )
    for destination in BackupDestination.objects.filter(enabled=True, retired_at=None):
        copies = uploads.filter(destination=destination)
        latest = copies.order_by("-created_at").first()
        failing = copies.exclude(state="deleted").filter(
            Q(state="abandoned") | ~Q(last_error_code=""),
        ).exists()
        # Probe results are deployment-global audit events. Do not use the
        # destination's last_error_code: a hidden tenant's upload can set it.
        probe = AuditLog.objects.filter(
            action="backup.destination_probed", target_type="backup.backupdestination",
            target_id=str(destination.pk), makerspace__isnull=True,
        ).order_by("-created_at", "-pk").values_list("meta", flat=True).first()
        probe_failed = bool(probe and probe.get("ok") is False)
        results.append({
            "name": destination.name,
            "state": latest.state if latest else "never",
            "verified_at": latest.verified_at if latest else None,
            "has_error": failing or probe_failed,
        })
    return results
