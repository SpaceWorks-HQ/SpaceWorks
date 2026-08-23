"""Fail-closed equality checks performed under the E5 promotion locks."""

import hmac

from apps.backup.activation_integrity import state_matches_flag
from apps.backup.artifact_ledger import ArtifactLedgerMismatch, component_specs
from apps.backup.models import (
    BackupArchive,
    BackupArtifactLedger,
    MakerspaceArchiveCustodyState,
)
from apps.backup.outer_manifest import manifest_digest, verify_outer_manifest
from apps.backup.recipients import fingerprint_for


def validate_frozen_state(
    artifact, spaces, recipients, activations, settings_row, artifacts
):
    snapshot = artifact.frozen_promotion_snapshot["retained"]
    expected_ids = {item["makerspace_id"] for item in snapshot}
    manifest_sets = artifact.outer_manifest["makerspace_sets"]
    if expected_ids != set(manifest_sets["retained"]):
        raise ArtifactLedgerMismatch(
            "The signed manifest and frozen makerspace population differ."
        )
    if set(spaces) != expected_ids or set(activations) != expected_ids:
        raise ArtifactLedgerMismatch("The retained makerspace population changed.")
    from apps.makerspaces.models import Makerspace

    if set(Makerspace.objects.values_list("pk", flat=True)) != expected_ids:
        raise ArtifactLedgerMismatch("The complete retained makerspace set changed.")

    by_space = _valid_recipients_by_space(recipients)
    signed_slices = {
        item["makerspace_id"]: sorted(item["recipient_fingerprints"])
        for item in artifact.outer_manifest["slice_components"]
    }
    custody = dict(
        MakerspaceArchiveCustodyState.objects.filter(
            makerspace_id__in=expected_ids
        ).values_list("makerspace_id", "state")
    )
    sovereign_ids = set(manifest_sets["sovereign"])
    for frozen in snapshot:
        makerspace_id = frozen["makerspace_id"]
        if not state_matches_flag(
            frozen["superadmin_access_enabled"], frozen["activation_state"]
        ):
            raise ArtifactLedgerMismatch(
                "A frozen access flag and activation state diverge."
            )
        if (
            spaces[makerspace_id].superadmin_access_enabled
            != frozen["superadmin_access_enabled"]
            or activations[makerspace_id].state != frozen["activation_state"]
        ):
            raise ArtifactLedgerMismatch("A frozen access or activation state changed.")
        if not state_matches_flag(
            spaces[makerspace_id].superadmin_access_enabled,
            activations[makerspace_id].state,
        ):
            raise ArtifactLedgerMismatch(
                "A current access flag and activation state diverge."
            )
        is_sovereign = not frozen["superadmin_access_enabled"]
        if is_sovereign != (makerspace_id in sovereign_ids):
            raise ArtifactLedgerMismatch(
                "The signed manifest and frozen sovereign population differ."
            )
        if not is_sovereign:
            continue
        current_recipients = sorted(
            by_space.get(makerspace_id, ()), key=lambda item: item["pk"]
        )
        if current_recipients != frozen["recipients"]:
            raise ArtifactLedgerMismatch("A frozen archive recipient set changed.")
        if sorted(item["fingerprint"] for item in frozen["recipients"]) != signed_slices.get(
            makerspace_id
        ):
            raise ArtifactLedgerMismatch(
                "The signed slice and frozen recipient set differ."
            )
        if custody.get(makerspace_id) != frozen["custody_state"]:
            raise ArtifactLedgerMismatch("A frozen archive custody state changed.")
    if settings_row.last_success_at != artifact.predecessor_success_at_snapshot:
        raise ArtifactLedgerMismatch("The predecessor backup success state changed.")
    predecessor_id = artifact.predecessor_artifact_id_snapshot
    if predecessor_id and (
        predecessor_id not in artifacts
        or artifacts[predecessor_id].state != BackupArtifactLedger.State.AVAILABLE
    ):
        raise ArtifactLedgerMismatch("The predecessor artifact state changed.")


def validate_artifact_rows(artifact, archive, components, associations):
    manifest = artifact.outer_manifest
    verify_outer_manifest(manifest)
    if (
        manifest["artifact_id"] != str(artifact.artifact_id)
        or manifest["capture_id"] != str(artifact.capture_id)
        or manifest["format"] != artifact.format
        or manifest_digest(manifest) != artifact.outer_manifest_sha256
        or archive.pk != artifact.archive_uuid_snapshot
        or archive.status != BackupArchive.Status.RUNNING
    ):
        raise ArtifactLedgerMismatch("The artifact or archive identity changed.")
    expected = component_specs(manifest)
    actual = {str(item.component_id): item for item in components}
    if set(actual) != {str(item["component_id"]) for item in expected}:
        raise ArtifactLedgerMismatch("The durable component set changed.")
    recipients_by_component = {}
    for row in associations:
        if row.tombstoned_at is None:
            recipients_by_component.setdefault(row.component_id, []).append(row.fingerprint)
    for item in expected:
        row = actual[str(item["component_id"])]
        if (
            row.kind != item["kind"]
            or row.makerspace_id_snapshot != item["makerspace_id_snapshot"]
            or row.ciphertext_path != item["ciphertext_path"]
            or row.size_bytes != item["size_bytes"]
            or not hmac.compare_digest(row.ciphertext_sha256, item["ciphertext_sha256"])
            or sorted(recipients_by_component.get(row.pk, ()))
            != sorted(item["recipient_fingerprints"])
        ):
            raise ArtifactLedgerMismatch("A component or recipient association changed.")


def _valid_recipients_by_space(recipients):
    result = {}
    for recipient in recipients:
        if (
            recipient.verified_at is not None
            and recipient.revoked_at is None
            and recipient.compromised_at is None
        ):
            if fingerprint_for(recipient.public_recipient) != recipient.fingerprint:
                raise ArtifactLedgerMismatch("A current recipient fingerprint is invalid.")
            result.setdefault(recipient.makerspace_id, []).append(
                {"pk": recipient.pk, "fingerprint": recipient.fingerprint}
            )
    return result
