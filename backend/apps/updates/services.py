from pathlib import PurePath

from django.db import transaction
from django.utils import timezone

from apps.updates.models import PlatformUpdateSettings
from apps.updates.recovery import INTERRUPTED_MESSAGE, mark_interrupted
from apps.updates.releases import release_allowed, select_release


@transaction.atomic
def queue_update():
    settings = _locked_settings()
    _require_no_rollback(settings)
    if settings.status != PlatformUpdateSettings.Status.RUNNING:
        settings.status = PlatformUpdateSettings.Status.QUEUED
        settings.update_requested_at = timezone.now()
        settings.last_error = ""
        settings.save(
            update_fields=(
                "status",
                "update_requested_at",
                "last_error",
                "updated_at",
            )
        )
    return settings


@transaction.atomic
def claim_update(*, current_version, available_version, force=False):
    settings = _locked_settings()
    return _claim_locked(settings, current_version, available_version, force)


@transaction.atomic
def claim_release(*, current_version, releases, force=False):
    settings = _locked_settings()
    release = select_release(releases)
    settings.release_notes = release["notes"]
    settings.release_url = release["url"]
    claimed = _claim_locked(settings, current_version, release["version"], force)
    return claimed, release["version"]


def _claim_locked(settings, current_version, available_version, force):
    _require_no_rollback(settings)
    if not release_allowed(available_version):
        raise ValueError("The release must be an immutable main release version.")
    if settings.status == PlatformUpdateSettings.Status.RUNNING:
        # The host only claims while holding the update lock, so a RUNNING row seen here
        # belongs to a run that died before its cleanup trap fired (host reboot, OOM kill).
        # Left alone it is RUNNING forever and the console disables both controls; record
        # it as the failure it was, then decide this run normally.
        mark_interrupted(settings)
    settings.current_version = current_version
    settings.available_version = available_version
    settings.last_checked_at = timezone.now()

    should_update = (
        current_version != available_version
        and (
            force
            or settings.automatic_updates_enabled
            or settings.status == PlatformUpdateSettings.Status.QUEUED
        )
    )
    if should_update:
        settings.status = PlatformUpdateSettings.Status.RUNNING
        settings.target_version = available_version
        settings.update_requested_at = None
        settings.last_error = ""
        settings.running_since = timezone.now()
        # A failed snapshot must never offer an older update's restore point.
        settings.pre_update_archive = None
        settings.pre_update_version = current_version
        settings.rollback_restore = None
    elif current_version == available_version:
        settings.status = PlatformUpdateSettings.Status.IDLE
        settings.target_version = ""
        settings.update_requested_at = None
        settings.last_error = ""
        settings.running_since = None
    settings.save()
    return should_update


@transaction.atomic
def record_backup(name):
    settings = _locked_settings()
    settings.last_backup_name = PurePath(name).name[:120]
    settings.last_backup_at = timezone.now()
    settings.save(
        update_fields=("last_backup_name", "last_backup_at", "updated_at")
    )
    return settings


@transaction.atomic
def complete_update(version):
    if not release_allowed(version):
        raise ValueError("The release must be an immutable main release version.")
    settings = _locked_settings()
    settings.status = PlatformUpdateSettings.Status.IDLE
    settings.current_version = version
    settings.available_version = version
    settings.target_version = ""
    settings.running_since = None
    settings.update_requested_at = None
    settings.last_updated_at = timezone.now()
    settings.last_error = ""
    settings.save()
    return settings


@transaction.atomic
def fail_update(message):
    settings = _locked_settings()
    settings.status = PlatformUpdateSettings.Status.FAILED
    settings.target_version = ""
    settings.running_since = None
    settings.last_error = str(message).strip()[:500]
    settings.save(
        update_fields=("status", "target_version", "running_since", "last_error", "updated_at")
    )
    return settings


def _locked_settings():
    PlatformUpdateSettings.objects.get_or_create(pk=1)
    return PlatformUpdateSettings.objects.select_for_update().get(pk=1)


def _require_no_rollback(settings):
    from apps.updates.rollback import active_rollback, refuse

    if active_rollback(settings):
        refuse("rollback_active", "A rollback restore is already active.")
