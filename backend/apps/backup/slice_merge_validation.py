"""Fail-closed outer and plaintext validation for delayed slice merges."""

import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import tarfile
import uuid

from apps.backup.compound_archive import COMPOUND_ARCHIVE_FORMAT
from apps.backup.digests import build_content_ledger, sha256_file
from apps.backup.outer_manifest import manifest_digest, verify_outer_manifest
from apps.backup.slice_merge_types import SliceMergeError
from apps.data_export.datasets import DATASET_SPECS


def validate_outer(operation, component, manifest, ciphertext, fingerprint):
    """Perform every step-one check before any slice plaintext is produced."""
    try:
        verify_outer_manifest(manifest)
    except Exception:
        raise SliceMergeError("The signed outer manifest is invalid.") from None
    try:
        fact = next(
            item for item in manifest["slice_components"]
            if item["component_id"] == str(component.component_id)
        )
        identities_match = (
            manifest["artifact_id"] == str(operation.artifact_id)
            and manifest["capture_id"] == str(operation.capture_id)
            and manifest_digest(manifest) == operation.outer_manifest_sha256
            and component.operation_id == operation.operation_id
            and component.artifact_id == operation.artifact_id
            and component.capture_id == operation.capture_id
            and fact["makerspace_id"] == component.makerspace_id_snapshot
        )
    except (KeyError, StopIteration, TypeError):
        identities_match = False
        fact = None
    if not identities_match:
        raise SliceMergeError("The artifact, capture, or component identity does not match.")
    try:
        actual_size = Path(ciphertext).stat().st_size
        actual_digest = sha256_file(ciphertext)
    except OSError:
        raise SliceMergeError("The stored component ciphertext is unavailable.") from None
    if (
        actual_size != fact["size_bytes"]
        or not hmac.compare_digest(actual_digest, fact["ciphertext_sha256"])
        or not hmac.compare_digest(actual_digest, component.ciphertext_sha256)
    ):
        raise SliceMergeError("The stored component ciphertext digest does not match.")
    if fingerprint not in fact["recipient_fingerprints"]:
        raise SliceMergeError("The tenant identity does not match this component recipient.")
    return fact


def extract_slice(plain_tar, root):
    """Extract regular files only, beneath a mode-0700 operation directory."""
    root = Path(root).resolve()
    try:
        with tarfile.open(plain_tar, "r:") as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise SliceMergeError("The decrypted slice contains an unsafe path.")
                if not (member.isdir() or member.isfile()):
                    raise SliceMergeError("The decrypted slice contains a non-regular member.")
                destination = root.joinpath(*relative.parts).resolve()
                try:
                    destination.relative_to(root)
                except ValueError:
                    raise SliceMergeError("The decrypted slice contains an unsafe path.") from None
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise SliceMergeError("The decrypted slice member is unreadable.")
                with destination.open("xb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
    except SliceMergeError:
        raise
    except (OSError, tarfile.TarError):
        raise SliceMergeError("The decrypted slice archive is invalid.") from None


def validate_plaintext(root, component, outer_fact, outer_manifest):
    """Re-run the target-relevant pre-seal checks over raw, unmapped bytes."""
    root = Path(root)
    manifest = _read_mapping(root / "slice-manifest.json", "detailed slice manifest")
    expected_keys = {
        "format", "slice_id", "makerspace_id", "recipient_fingerprints",
        "custody_state", "storage", "sealed_deks",
    }
    if (
        set(manifest) != expected_keys
        or manifest["format"] != COMPOUND_ARCHIVE_FORMAT
        or manifest["slice_id"] != str(component.component_id)
        or manifest["makerspace_id"] != component.makerspace_id_snapshot
        or manifest["recipient_fingerprints"] != outer_fact["recipient_fingerprints"]
        or set(manifest.get("storage", {})) != {"objects"}
    ):
        raise SliceMergeError("The detailed slice manifest does not match its component.")
    _validate_rows(root / "rows")
    _validate_objects(root / "objects", manifest["storage"]["objects"])
    ledger = build_content_ledger(root)
    ledger_fact = next(
        item for item in outer_manifest["content_ledgers"]
        if item["component_id"] == str(component.component_id)
    )
    object_fact = next(
        item for item in outer_manifest["object_ledgers"]
        if item["component_id"] == str(component.component_id)
    )
    if (
        ledger_fact["count"] != len(ledger)
        or ledger_fact["digest"] != _digest(ledger)
        or object_fact["count"] != len(manifest["storage"]["objects"])
        or object_fact["digest"] != _digest(manifest["storage"]["objects"])
    ):
        raise SliceMergeError("The detailed slice content ledger does not match the outer manifest.")
    return manifest


def dependency_facts(root, component, outer_manifest):
    components = {
        item["makerspace_id"]: item["component_id"]
        for item in outer_manifest["slice_components"]
    }
    own = component.makerspace_id_snapshot
    references = _read_list(Path(root) / "rows" / "external_references.json", "dependency ledger")
    found = {}
    for item in references:
        target = item.get("field_preimage")
        if type(target) is int and target in components and target != own:
            found[components[target]] = "declared_external_reference"
        elif item.get("type") in {
            "hosted_event_collaborator", "foreign_host_event", "inbound_stock_transfer"
        }:
            for makerspace_id, component_id in components.items():
                if makerspace_id != own:
                    found.setdefault(component_id, "conservative_semantic_reference")
    return [{"component_id": key, "reason": found[key]} for key in sorted(found)]


def _validate_rows(root):
    expected = {f"{label.lower().replace('.', '_')}.json" for label in DATASET_SPECS}
    expected |= {"external_references.json", "global_user_references.json"}
    actual = {path.name for path in root.iterdir() if path.is_file()}
    if actual != expected:
        raise SliceMergeError("The slice raw dataset set is incomplete or contains extras.")
    for label in DATASET_SPECS:
        values = _read_list(root / f"{label.lower().replace('.', '_')}.json", "raw dataset")
        seen = set()
        for item in values:
            if set(item) != {"model", "pk", "fields"} or item["model"] != label.lower():
                raise SliceMergeError("A slice raw dataset contains a substituted row.")
            identity = json.dumps(item["pk"], sort_keys=True, default=str)
            if identity in seen or not isinstance(item["fields"], dict):
                raise SliceMergeError("A slice raw dataset contains a duplicate row.")
            seen.add(identity)


def _validate_objects(root, objects):
    seen = set()
    for item in objects:
        required = {
            "bucket_kind", "key", "version_id", "size", "sha256", "metadata",
            "content_type", "headers",
        }
        if not required.issubset(item) or set(item) - required > {
            "makerspace_id", "module_key",
        }:
            raise SliceMergeError("The slice object manifest is malformed.")
        key = PurePosixPath(str(item["key"]))
        if (
            item["bucket_kind"] not in {"private", "public_image"}
            or key.is_absolute() or not key.parts or ".." in key.parts
        ):
            raise SliceMergeError("The slice object manifest contains an unsafe key.")
        identity = (item["bucket_kind"], item["key"])
        if identity in seen:
            raise SliceMergeError("The slice object manifest contains a duplicate object.")
        seen.add(identity)
        path = root.joinpath(item["bucket_kind"], *key.parts)
        try:
            valid = path.is_file() and path.stat().st_size == item["size"] and sha256_file(path) == item["sha256"]
        except OSError:
            valid = False
        if not valid:
            raise SliceMergeError("A slice object byte does not match its immutable manifest.")


def _read_mapping(path, label):
    value = _read_json(path, label)
    if not isinstance(value, dict):
        raise SliceMergeError(f"The {label} is not an object.")
    return value


def _read_list(path, label):
    value = _read_json(path, label)
    if not isinstance(value, list):
        raise SliceMergeError(f"The {label} is not a list.")
    return value


def _read_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SliceMergeError(f"The {label} is unreadable.") from None


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()).hexdigest()
