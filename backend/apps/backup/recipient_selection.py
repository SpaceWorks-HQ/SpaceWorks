"""Recipient selection for locally built backup archives."""

from django.conf import settings

from apps.makerspaces.models import Makerspace

from .models import BackupArchive, MakerspaceArchiveRecipient


PLATFORM_RECIPIENT_LABEL = "Platform backup recipient"


class BackupBuildError(RuntimeError):
    pass


def selection_for(archive) -> list[dict]:
    """Return the deterministic, verified recipient list for one archive."""
    if archive.scope == BackupArchive.Scope.DEPLOYMENT:
        return [_platform_recipient()]

    selected = list(
        MakerspaceArchiveRecipient.objects.filter(
            makerspace_id=archive.makerspace_id,
            revoked_at__isnull=True,
            compromised_at__isnull=True,
            verified_at__isnull=False,
        )
        .order_by("pk")
        .values("label", "public_recipient")
    )
    if _superadmin_access_decision(archive):
        selected.append(_platform_recipient())
    if not selected:
        raise BackupBuildError(
            "No verified archive recipient is available for this makerspace."
        )
    return selected


def _platform_recipient():
    public_recipient = settings.BACKUP_AGE_RECIPIENT
    if not public_recipient:
        raise BackupBuildError(
            "BACKUP_AGE_RECIPIENT is required before backups can run."
        )
    return {
        "label": PLATFORM_RECIPIENT_LABEL,
        "public_recipient": public_recipient,
    }


def _superadmin_access_decision(archive):
    decided = getattr(archive, "superadmin_access_at_decision", None)
    if decided is not None:
        return decided
    return Makerspace.objects.values_list(
        "superadmin_access_enabled", flat=True
    ).get(pk=archive.makerspace_id)
