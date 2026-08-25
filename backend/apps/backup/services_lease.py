from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.backup.models import BackupLease, BackupRun


@transaction.atomic
def _claim_lease(holder):
    row, _ = BackupLease.objects.select_for_update().get_or_create(
        name="deployment-backup"
    )
    now = timezone.now()
    if row.leased_until and row.leased_until > now:
        return False
    row.holder = holder
    row.leased_until = now + timedelta(seconds=settings.BACKUP_LEASE_SECONDS)
    row.save(update_fields=("holder", "leased_until", "updated_at"))
    return True


@transaction.atomic
def _renew_lease(holder):
    leased_until = timezone.now() + timedelta(seconds=settings.BACKUP_LEASE_SECONDS)
    renewed = BackupLease.objects.filter(
        name="deployment-backup", holder=holder
    ).update(leased_until=leased_until)
    BackupRun.objects.filter(
        holder=holder,
        status__in=(BackupRun.Status.PENDING, BackupRun.Status.RUNNING),
    ).update(leased_until=leased_until)
    return bool(renewed)


@transaction.atomic
def _release_lease(holder):
    BackupLease.objects.filter(name="deployment-backup", holder=holder).update(
        holder=None, leased_until=None
    )
    BackupRun.objects.filter(holder=holder).update(leased_until=None)
