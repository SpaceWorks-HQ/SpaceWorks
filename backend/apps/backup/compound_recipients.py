"""Frozen sovereign slice recipients selected inside the archive snapshot."""

from dataclasses import dataclass
import uuid

from apps.backup.models import (
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.makerspaces.models import Makerspace


@dataclass(frozen=True)
class FrozenSlice:
    makerspace_id: int
    slice_id: str
    public_recipients: tuple[str, ...]
    recipient_fingerprints: tuple[str, ...]
    custody_state: str


def frozen_slices(archive_id, platform_recipients):
    makerspace_ids = tuple(
        Makerspace.objects.filter(superadmin_access_enabled=False)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    recipient_rows = MakerspaceArchiveRecipient.objects.filter(
        makerspace_id__in=makerspace_ids,
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).order_by("makerspace_id", "pk").values_list(
        "makerspace_id", "public_recipient"
    )
    by_makerspace = {makerspace_id: [] for makerspace_id in makerspace_ids}
    for makerspace_id, public_recipient in recipient_rows:
        by_makerspace[makerspace_id].append(public_recipient)
    custody = dict(
        MakerspaceArchiveCustodyState.objects.filter(
            makerspace_id__in=makerspace_ids
        ).values_list("makerspace_id", "state")
    )

    result = []
    for makerspace_id in makerspace_ids:
        public_recipients = tuple(by_makerspace[makerspace_id])
        if not public_recipients:
            raise BackupBuildError(
                "A sovereign makerspace has no valid archive recipient."
            )
        fingerprints = tuple(sorted(
            fingerprint_for(value) for value in public_recipients
        ))
        if len(set(fingerprints)) != len(fingerprints):
            raise BackupBuildError(
                "A sovereign makerspace has duplicate archive recipients."
            )
        if platform_recipients.intersection(public_recipients):
            raise BackupBuildError(
                "A platform archive recipient cannot be used for a sovereign slice."
            )
        expected_custody = (
            MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT
            if len(public_recipients) == 1
            else MakerspaceArchiveCustodyState.State.HEALTHY
        )
        if (
            len(public_recipients) == 1
            and custody.get(makerspace_id) != expected_custody
        ):
            raise BackupBuildError(
                "A one-recipient sovereign makerspace lacks its degraded custody state."
            )
        result.append(FrozenSlice(
            makerspace_id=makerspace_id,
            slice_id=str(uuid.uuid5(
                archive_id, f"sovereign-slice:{makerspace_id}"
            )),
            public_recipients=public_recipients,
            recipient_fingerprints=fingerprints,
            custody_state=expected_custody,
        ))
    return tuple(result)
