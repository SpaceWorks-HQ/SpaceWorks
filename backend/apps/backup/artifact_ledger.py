"""Idempotent persistence and pre-promotion state transitions for Lane E."""

import hmac

from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.backup.models import (
    BackupArtifactComponent,
    BackupArtifactLedger,
    BackupComponentRecipient,
)
from apps.backup.outer_manifest import manifest_digest, verify_outer_manifest
from apps.backup.storage_promotion import final_locator, staging_locator


class ArtifactLedgerMismatch(RuntimeError):
    pass


@transaction.atomic
def persist_pending(archive, build, size_bytes):
    manifest = build.manifest
    if build.promotion_snapshot is None:
        raise ArtifactLedgerMismatch("A compound artifact has no frozen promotion snapshot.")
    verify_outer_manifest(manifest)
    snapshot = build.promotion_snapshot
    predecessor_id = snapshot.get("predecessor_artifact_id")
    predecessor_success = snapshot.get("predecessor_success_at")
    predecessor_success_at = (
        parse_datetime(predecessor_success) if predecessor_success else None
    )
    facts = {
        "capture_id": manifest["capture_id"],
        "archive": archive,
        "archive_uuid_snapshot": archive.pk,
        "outer_sha256": build.archive_sha256,
        "outer_manifest_sha256": manifest_digest(manifest),
        "format": manifest["format"],
        "outer_manifest": manifest,
        "frozen_promotion_snapshot": build.promotion_snapshot,
        "expected_size_bytes": size_bytes,
        "staging_locator": archive.staging_object_key or staging_locator(archive.pk),
        "final_locator": final_locator(archive.pk),
        "predecessor_artifact_id_snapshot": predecessor_id,
        "predecessor_success_at_snapshot": predecessor_success_at,
    }
    ledger, created = BackupArtifactLedger.objects.get_or_create(
        artifact_id=archive.pk, defaults=facts
    )
    if not created:
        _require_equal(ledger, facts)
    specs = component_specs(manifest)
    for declared in specs:
        spec = dict(declared)
        recipients = tuple(spec.pop("recipient_fingerprints"))
        component, component_created = BackupArtifactComponent.objects.get_or_create(
            artifact=ledger,
            component_id=spec["component_id"],
            defaults=spec,
        )
        if not component_created:
            _require_equal(component, spec)
        for fingerprint in recipients:
            BackupComponentRecipient.objects.get_or_create(
                component=component, fingerprint=fingerprint
            )
        actual_recipients = set(
            component.recipient_associations.filter(
                tombstoned_at__isnull=True
            ).values_list("fingerprint", flat=True)
        )
        if actual_recipients != set(recipients):
            raise ArtifactLedgerMismatch(
                "The durable component recipient set differs from the manifest."
            )
    if ledger.components.count() != len(specs):
        raise ArtifactLedgerMismatch("The durable component set differs from the manifest.")
    return ledger


def component_specs(manifest):
    main = manifest["main_component"]
    values = [{
        "component_id": main["component_id"],
        "kind": BackupArtifactComponent.Kind.MAIN,
        "makerspace_id_snapshot": None,
        "ciphertext_path": main["path"],
        "ciphertext_sha256": main["ciphertext_sha256"],
        "size_bytes": main["size_bytes"],
        "recipient_fingerprints": tuple(main["recipient_fingerprints"]),
    }]
    values.extend({
        "component_id": item["component_id"],
        "kind": BackupArtifactComponent.Kind.SLICE,
        "makerspace_id_snapshot": item["makerspace_id"],
        "ciphertext_path": item["ciphertext_path"],
        "ciphertext_sha256": item["ciphertext_sha256"],
        "size_bytes": item["size_bytes"],
        "recipient_fingerprints": tuple(item["recipient_fingerprints"]),
    } for item in manifest["slice_components"])
    return values


@transaction.atomic
def mark_staging_verified(artifact_id, size_bytes, sha256):
    row = BackupArtifactLedger.objects.select_for_update().get(pk=artifact_id)
    if row.state == BackupArtifactLedger.State.STAGING_VERIFIED:
        _require_verification(row, "staging", size_bytes, sha256)
        return row
    if row.state != BackupArtifactLedger.State.PENDING:
        raise ArtifactLedgerMismatch("Staging verification conflicts with artifact state.")
    row.state = BackupArtifactLedger.State.STAGING_VERIFIED
    row.staging_verified_at = timezone.now()
    row.staging_verified_size_bytes = size_bytes
    row.staging_verified_sha256 = sha256
    row.save(update_fields=(
        "state", "staging_verified_at", "staging_verified_size_bytes",
        "staging_verified_sha256",
    ))
    return row


@transaction.atomic
def mark_final_verified(artifact_id, size_bytes, sha256):
    row = BackupArtifactLedger.objects.select_for_update().get(pk=artifact_id)
    if row.state == BackupArtifactLedger.State.FINAL_VERIFIED:
        _require_verification(row, "final", size_bytes, sha256)
        return row
    if row.state not in {
        BackupArtifactLedger.State.PENDING,
        BackupArtifactLedger.State.STAGING_VERIFIED,
    }:
        raise ArtifactLedgerMismatch("Final verification conflicts with artifact state.")
    row.state = BackupArtifactLedger.State.FINAL_VERIFIED
    row.final_verified_at = timezone.now()
    row.final_verified_size_bytes = size_bytes
    row.final_verified_sha256 = sha256
    row.save(update_fields=(
        "state", "final_verified_at", "final_verified_size_bytes",
        "final_verified_sha256",
    ))
    return row


@transaction.atomic
def mark_failed(artifact_id, code):
    row = BackupArtifactLedger.objects.select_for_update().filter(pk=artifact_id).first()
    if row is None or row.state in {
        BackupArtifactLedger.State.AVAILABLE,
        BackupArtifactLedger.State.SUPERSEDED,
        BackupArtifactLedger.State.BYTES_DELETED,
    }:
        return False
    if row.state == BackupArtifactLedger.State.FAILED:
        return True
    row.state = BackupArtifactLedger.State.FAILED
    row.failure_code = str(code)[:64]
    row.failed_at = timezone.now()
    row.cleanup_pending = True
    row.save(update_fields=("state", "failure_code", "failed_at", "cleanup_pending"))
    return True


@transaction.atomic
def mark_cleanup_complete(artifact_id):
    row = BackupArtifactLedger.objects.select_for_update().get(pk=artifact_id)
    if row.cleanup_pending:
        row.cleanup_pending = False
        row.save(update_fields=("cleanup_pending",))
    return row


@transaction.atomic
def mark_managed_bytes_deleted(artifact_id):
    row = BackupArtifactLedger.objects.select_for_update().get(pk=artifact_id)
    if row.state == BackupArtifactLedger.State.BYTES_DELETED:
        return row
    if row.state not in {
        BackupArtifactLedger.State.AVAILABLE,
        BackupArtifactLedger.State.SUPERSEDED,
    }:
        raise ArtifactLedgerMismatch("Only promoted managed bytes can be deleted.")
    now = timezone.now()
    BackupArtifactComponent.objects.filter(artifact=row).update(
        storage_state=BackupArtifactComponent.StorageState.BYTES_DELETED,
        bytes_deleted_at=now,
    )
    BackupComponentRecipient.objects.filter(
        component__artifact=row, tombstoned_at__isnull=True
    ).update(tombstoned_at=now)
    row.state = BackupArtifactLedger.State.BYTES_DELETED
    row.bytes_deleted_at = now
    row.cleanup_pending = False
    row.save(update_fields=("state", "bytes_deleted_at", "cleanup_pending"))
    return row


def _require_equal(instance, expected):
    for field, value in expected.items():
        actual = getattr(instance, f"{field}_id", None) if field == "archive" else getattr(instance, field)
        expected_value = value.pk if field == "archive" else value
        if field in {
            "capture_id", "archive_uuid_snapshot", "component_id",
            "predecessor_artifact_id_snapshot",
        }:
            equal = (
                actual is None and expected_value is None
            ) or str(actual) == str(expected_value)
        elif field.endswith("sha256"):
            equal = hmac.compare_digest(str(actual), str(expected_value))
        else:
            equal = actual == expected_value
        if not equal:
            raise ArtifactLedgerMismatch(
                f"The durable {instance._meta.label_lower} {field} fact differs."
            )


def _require_verification(row, prefix, size_bytes, sha256):
    if (
        getattr(row, f"{prefix}_verified_size_bytes") != size_bytes
        or not hmac.compare_digest(
            getattr(row, f"{prefix}_verified_sha256"), sha256
        )
    ):
        raise ArtifactLedgerMismatch(
            f"The repeated {prefix} verification facts differ."
        )
