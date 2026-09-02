"""Legacy object collection plus immutable object-byte capture."""

from django.apps import apps
from django.conf import settings

from apps.backup import storage
from apps.data_export.datasets import DATASET_SPECS


OBJECT_FIELD_NAMES = frozenset({
    "object_key", "image_key", "avatar_key", "cover_image_key", "copy_key",
    "logo_key",
})

NON_OBJECT_KEY_FIELDS = frozenset({
    ("accounts.NativeAppRegistration", "verifier_config_key"),
    ("accounts.PlatformSocialAuthSettings", "apple_private_key"),
    ("audit.AuditMacKey", "wrapped_key"),
    ("audit.AuditSigningKey", "public_key"),
    ("audit.AuditSigningKey", "wrapped_private_key"),
    ("audit.AuditSigningKeyRotation", "new_key"),
    ("audit.AuditSigningKeyRotation", "old_key"),
    ("backup.RestoreRollbackObject", "module_key"),
    ("backup.RestoreRollbackObject", "source_key"),
    # Run-owned promotion staging is retry coordination, not durable archive
    # content. The final object and artifact ledger are the restore authority.
    ("backup.BackupArchive", "staging_object_key"),
    ("integrations.PlatformPushSettings", "apns_private_key"),
    ("makerspaces.Makerspace", "public_api_key"),
    ("payments.MakerspacePaymentSettings", "stripe_publishable_key"),
    ("payments.MakerspacePaymentSettings", "stripe_secret_key"),
    ("payments.PlatformStripeConnectSettings", "stripe_publishable_key"),
    ("payments.PlatformStripeConnectSettings", "stripe_secret_key"),
    ("sessions.Session", "session_key"),
    ("tenant_migration.DeploymentSigningKey", "public_key"),
    ("tenant_migration.MigrationPairing", "source_public_key"),
    ("tenant_migration.MigrationPairing", "target_public_key"),
    # Transient staging locator for an exit artifact that was never published.
    # The bytes are deleted on refusal and renamed on publication, so a captured
    # copy would restore as a pointer to something that must not exist.
    ("tenant_migration.TenantDumpCapture", "unpublished_object_key"),
    ("tenant_migration.TenantImportObject", "source_key"),
    ("tenant_migration.TenantImportObject", "staging_key"),
    ("tenant_migration.TenantImportObject", "target_key"),
})


def object_closure():
    """Compatibility closure for non-compound makerspace archives."""
    result = {"private": {}, "public_image": {}}
    for model in apps.get_models():
        collect_model_objects(model._default_manager.all(), model, result)
    return result


def collect_model_objects(queryset, model, result, fixed_makerspace_id=None):
    spec = DATASET_SPECS.get(model._meta.label)
    ownership_paths = spec[1].any_paths if spec else ()
    if not ownership_paths and any(
        field.name == "makerspace" for field in model._meta.concrete_fields
    ):
        ownership_paths = ("makerspace",)
    for field in model._meta.concrete_fields:
        if field.name not in OBJECT_FIELD_NAMES:
            continue
        if model._meta.label == "evidence.EvidencePhoto" and field.name == "object_key":
            _collect_evidence_objects(queryset, result, fixed_makerspace_id)
            continue
        if field.name == "copy_key":
            rows = queryset.exclude(copy_key="").values_list(
                "copy_key", "bucket_kind", "makerspace_id", "module_key"
            )
            for key, kind, owner, module_key in rows:
                result[kind][str(key)] = {
                    "makerspace_id": owner, "module_key": module_key,
                }
            continue
        bucket_kind = "public_image" if field.name != "object_key" else "private"
        value_paths = [
            path if path in {"pk", "id"} else f"{path}_id"
            for path in ownership_paths
        ]
        rows = queryset.exclude(**{field.name: ""}).values_list(
            field.name, *value_paths
        )
        for values in rows:
            key, *owners = values
            if key and not str(key).startswith("backup-archives/"):
                owner = fixed_makerspace_id or next(
                    (item for item in owners if item), None
                )
                result[bucket_kind][str(key)] = {
                    "makerspace_id": owner,
                    "module_key": module_for_model(model._meta.label),
                }


def _collect_evidence_objects(queryset, result, fixed_makerspace_id):
    rows = queryset.exclude(object_key="").values(
        "object_key",
        "makerspace_id",
        "object_retention_state__status",
        "object_retention_state__object_expired_at",
        "object_retention_state__expired_size_bytes",
    )
    for row in rows:
        status = row["object_retention_state__status"]
        if status == "expiring":
            raise storage.BackupStorageError(
                "Evidence expiry is in progress; retry the archive after it completes."
            )
        ownership = {
            "makerspace_id": fixed_makerspace_id or row["makerspace_id"],
            "module_key": "",
        }
        if status == "expired":
            expired_at = row["object_retention_state__object_expired_at"]
            if expired_at is None:
                raise storage.BackupStorageError(
                    "Expired evidence is missing its terminal timestamp."
                )
            ownership.update(
                retention_state="expired",
                object_expired_at=expired_at.isoformat(),
                expired_size_bytes=row[
                    "object_retention_state__expired_size_bytes"
                ],
            )
        result["private"][str(row["object_key"])] = ownership


def capture_objects(root, object_keys, modes):
    manifest = []
    buckets = {
        "private": settings.AWS_STORAGE_BUCKET_NAME,
        "public_image": settings.PUBLIC_IMAGE_BUCKET,
    }
    for kind, keys in object_keys.items():
        if kind not in buckets:
            raise ValueError(f"Unsupported backup bucket kind: {kind!r}.")
        for key, ownership in sorted(keys.items()):
            if ownership.get("retention_state") == "expired":
                storage.assert_object_absent(buckets[kind], key)
                storage.assert_object_absent(buckets[kind], f"staging/{key}")
                manifest.append(
                    {
                        "bucket_kind": kind,
                        **ownership,
                        "key": key,
                        "version_id": None,
                        "size": 0,
                        "sha256": "",
                        "metadata": {},
                        "content_type": "",
                        "headers": {},
                    }
                )
                continue
            destination = root / kind / key
            item = storage.download_object(
                buckets[kind], key, destination, versioned=modes[kind] == "versioned"
            )
            manifest.append({"bucket_kind": kind, **ownership, **item})
    return manifest


def module_for_model(label):
    return {
        "events.Event": "events",
        "bookings.BookableSpace": "bookings",
        "maintenance.MaintenanceLogDocument": "maintenance",
        "procurement.ToBuyReceipt": "procurement",
        "makerspaces.MemberProfile": "membership",
        "makerspaces.MemberProject": "membership",
        "machines.ServiceRequestFile": "machine_service",
    }.get(label, "")
