"""Frozen sovereign slice recipients selected inside the archive snapshot."""

from dataclasses import dataclass

from apps.backup.activation_integrity import state_matches_flag
from apps.backup.models import (
    B1ActivationState,
    BackupArtifactLedger,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    PlatformBackupSettings,
)
from apps.backup.outer_manifest import component_id
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
    activation_state: str = B1ActivationState.State.OFF_PENDING
    recipient_rows: tuple[tuple[int, str], ...] = ()


def frozen_population():
    makerspaces = tuple(
        Makerspace.objects.order_by("pk").values_list(
            "pk", "superadmin_access_enabled"
        )
    )
    activations = dict(
        B1ActivationState.objects.filter(
            makerspace_id__in=[item[0] for item in makerspaces]
        ).values_list("makerspace_id", "state")
    )
    if set(activations) != {item[0] for item in makerspaces}:
        raise BackupBuildError("The Lane E activation-state population is incomplete.")
    divergent = [
        makerspace_id
        for makerspace_id, access_enabled in makerspaces
        if not state_matches_flag(access_enabled, activations[makerspace_id])
    ]
    if divergent:
        raise BackupBuildError(
            "The Lane E access flag and activation state diverge."
        )
    return tuple({
        "makerspace_id": makerspace_id,
        "superadmin_access_enabled": access_enabled,
        "activation_state": activations[makerspace_id],
    } for makerspace_id, access_enabled in makerspaces)


def predecessor_snapshot():
    predecessor = BackupArtifactLedger.objects.filter(
        state=BackupArtifactLedger.State.AVAILABLE
    ).order_by("-promoted_at", "-created_at").first()
    last_success_at = PlatformBackupSettings.objects.filter(pk=1).values_list(
        "last_success_at", flat=True
    ).first()
    return {
        "predecessor_artifact_id": str(predecessor.artifact_id) if predecessor else None,
        "predecessor_success_at": last_success_at.isoformat() if last_success_at else None,
    }


def frozen_slices(capture_id, platform_recipients, population):
    makerspace_ids = tuple(
        item["makerspace_id"] for item in population
        if not item["superadmin_access_enabled"]
    )
    recipient_rows = MakerspaceArchiveRecipient.objects.filter(
        makerspace_id__in=makerspace_ids,
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).order_by("makerspace_id", "pk").values_list(
        "pk", "makerspace_id", "public_recipient", "fingerprint"
    )
    by_makerspace = {makerspace_id: [] for makerspace_id in makerspace_ids}
    for recipient_pk, makerspace_id, public_recipient, fingerprint in recipient_rows:
        if fingerprint_for(public_recipient) != fingerprint:
            raise BackupBuildError("A sovereign archive recipient fingerprint is invalid.")
        by_makerspace[makerspace_id].append(
            (recipient_pk, public_recipient, fingerprint)
        )
    custody = dict(
        MakerspaceArchiveCustodyState.objects.filter(
            makerspace_id__in=makerspace_ids
        ).values_list("makerspace_id", "state")
    )

    result = []
    activations = {
        item["makerspace_id"]: item["activation_state"] for item in population
    }
    for makerspace_id in makerspace_ids:
        rows = tuple(by_makerspace[makerspace_id])
        public_recipients = tuple(item[1] for item in rows)
        if not public_recipients:
            raise BackupBuildError(
                "A sovereign makerspace has no valid archive recipient."
            )
        fingerprints = tuple(sorted(item[2] for item in rows))
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
        if custody.get(makerspace_id) != expected_custody:
            raise BackupBuildError(
                "A sovereign makerspace lacks its exact derived custody state."
            )
        activation_state = activations[makerspace_id]
        if activation_state not in {
            B1ActivationState.State.OFF_PENDING,
            B1ActivationState.State.OFF_EFFECTIVE,
        }:
            raise BackupBuildError(
                "A switched-off makerspace has an invalid Lane E activation state."
            )
        result.append(FrozenSlice(
            makerspace_id=makerspace_id,
            slice_id=component_id(capture_id, "slice", makerspace_id),
            public_recipients=public_recipients,
            recipient_fingerprints=fingerprints,
            custody_state=expected_custody,
            activation_state=activation_state,
            recipient_rows=tuple((item[0], item[2]) for item in rows),
        ))
    return tuple(result)
