"""Pre-seal semantic checks for plaintext sovereign slices."""

import json
from pathlib import Path

from django.apps import apps

from apps.backup.digests import sha256_file
from apps.backup.main_projection_inverse import boundary_deltas
from apps.backup.raw_projection import canonical_owner_q, no_decrypt_guard, raw_records
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.tenant_projection import project_raw_dataset
from apps.data_export.datasets import DATASET_SPECS


def verify_unsealed_slice(makerspace_id, plaintext, object_manifest):
    """Compare plaintext rows to the frozen source and object bytes to their ledgers."""
    root = Path(plaintext)
    rows_root = root / "rows"
    expected_references = []
    referenced_users = set()
    with no_decrypt_guard():
        for label, (_path, predicate) in sorted(DATASET_SPECS.items()):
            model = apps.get_model(label)
            queryset = model.objects.filter(
                canonical_owner_q(predicate, makerspace_id)
            ).order_by(
                model._meta.pk.name
            )
            records = raw_records(queryset, model)
            expected, references, included_pks = project_raw_dataset(
                label, model, records, makerspace_id
            )
            payload_path = rows_root / f"{label.lower().replace('.', '_')}.json"
            try:
                actual = payload_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise BackupBuildError(
                    f"Sovereign slice is missing the raw dataset for {label}."
                ) from exc
            if actual != expected:
                raise BackupBuildError(
                    f"Sovereign slice row verification failed for {label}."
                )
            included = queryset.filter(pk__in=included_pks)
            expected_references.extend(references)
            for field in model._meta.fields:
                if (
                    field.remote_field
                    and field.remote_field.model._meta.label == "accounts.User"
                ):
                    referenced_users.update(
                        included.values_list(field.attname, flat=True)
                    )
    _verify_json(
        rows_root / "external_references.json", expected_references,
        "reference ledger",
    )
    User = apps.get_model("accounts.User")
    expected_users = list(
        User.objects.filter(pk__in=referenced_users).values("id", "username")
    )
    _verify_json(
        rows_root / "global_user_references.json", expected_users,
        "global-user reference ledger",
    )
    _verify_json(
        root / "inverse" / "boundary-deltas.json",
        boundary_deltas(makerspace_id),
        "boundary reversal ledger",
    )
    _verify_slice_manifest(root / "slice-manifest.json", makerspace_id, object_manifest)
    _verify_objects(root / "objects", object_manifest)


def _verify_json(path, expected, label):
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupBuildError(f"Sovereign slice {label} is invalid.") from exc
    normalized = json.loads(json.dumps(expected, default=str))
    if label == "global-user reference ledger":
        actual = sorted(actual, key=lambda item: str(item["id"]))
        normalized = sorted(normalized, key=lambda item: str(item["id"]))
    if actual != normalized:
        raise BackupBuildError(f"Sovereign slice {label} verification failed.")


def _verify_objects(root, manifest):
    for item in manifest:
        path = root / item["bucket_kind"] / item["key"]
        try:
            size = path.stat().st_size
            digest = sha256_file(path)
        except OSError as exc:
            raise BackupBuildError(
                "Sovereign slice object verification failed."
            ) from exc
        if size != item["size"] or digest != item["sha256"]:
            raise BackupBuildError(
                "Sovereign slice object verification failed."
            )


def _verify_slice_manifest(path, makerspace_id, objects):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        fingerprints = manifest["recipient_fingerprints"]
        valid = (
            manifest["makerspace_id"] == makerspace_id
            and isinstance(manifest["slice_id"], str)
            and manifest["storage"]["objects"] == objects
            and fingerprints
            and len(fingerprints) == len(set(fingerprints))
        )
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        valid = False
    if not valid:
        raise BackupBuildError("Sovereign slice manifest verification failed.")
