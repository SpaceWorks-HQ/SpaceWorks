"""Structural allowlist validation for the readable Lane E manifest."""

import uuid

from apps.backup.recipient_selection import BackupBuildError
from apps.backup.outer_reservation_validation import validate_reservation_manifest


def component_id(capture_id, kind, makerspace_id=None):
    namespace = uuid.UUID(str(capture_id))
    tenant = "" if makerspace_id is None else str(int(makerspace_id))
    return str(uuid.uuid5(namespace, f"component:{kind}:{tenant}"))


def validate_unsigned_manifest(manifest, *, protocol_version):
    try:
        if manifest["protocol_version"] != protocol_version:
            raise ValueError
        capture_id = uuid.UUID(str(manifest["capture_id"]))
        uuid.UUID(str(manifest["artifact_id"]))
        build_identity = manifest["build_identity"]
        postgres = manifest["postgres"]
        if (
            not isinstance(build_identity, dict)
            or set(build_identity) != {"build", "oci_digest"}
            or not isinstance(build_identity["build"], dict)
            or not isinstance(build_identity["build"].get("source_hash"), str)
            or not build_identity["build"]["source_hash"]
            or not isinstance(build_identity["oci_digest"], str)
            or not isinstance(postgres, dict)
            or set(postgres) != {
                "source_server_major", "client", "supported_source_majors"
            }
            or type(postgres["source_server_major"]) is not int
            or not 10 <= postgres["source_server_major"] <= 99
            or not isinstance(postgres["client"], str)
            or not postgres["client"]
            or not isinstance(postgres["supported_source_majors"], list)
            or postgres["supported_source_majors"]
            != sorted(set(postgres["supported_source_majors"]))
            or any(
                type(value) is not int or not 10 <= value <= 99
                for value in postgres["supported_source_majors"]
            )
            or postgres["source_server_major"]
            not in postgres["supported_source_majors"]
        ):
            raise ValueError
        sets = manifest["makerspace_sets"]
        retained = sets["retained"]
        readable = sets["readable_main"]
        sovereign = sets["sovereign"]
        if any(
            values != sorted(set(values))
            or any(type(value) is not int for value in values)
            or any(value <= 0 for value in values)
            for values in (retained, readable, sovereign)
        ):
            raise ValueError
        if set(readable).intersection(sovereign) or set(readable).union(
            sovereign
        ) != set(retained):
            raise ValueError
        main = manifest["main_component"]
        main_fingerprints = main["recipient_fingerprints"]
        if (
            main["kind"] != "main"
            or main["component_id"] != component_id(capture_id, "main")
            or not _is_digest(main["ciphertext_sha256"])
            or not _is_digest(main["schema_catalog_digest"])
            or not _is_digest(main["semantic_digest"])
            or main_fingerprints != sorted(set(main_fingerprints))
            or any(not _is_digest(value) for value in main_fingerprints)
        ):
            raise ValueError
        slices = manifest["slice_components"]
        if [item["makerspace_id"] for item in slices] != sovereign:
            raise ValueError
        components = [main, *slices]
        component_ids = []
        for item in slices:
            fingerprints = item["recipient_fingerprints"]
            if (
                item["kind"] != "slice"
                or item["component_id"]
                != component_id(capture_id, "slice", item["makerspace_id"])
                or fingerprints != sorted(set(fingerprints))
                or not fingerprints
                or not _is_digest(item["ciphertext_sha256"])
                or any(not _is_digest(value) for value in fingerprints)
            ):
                raise ValueError
        for item in components:
            component_ids.append(item["component_id"])
        if len(component_ids) != len(set(component_ids)):
            raise ValueError
        expected_ids = set(component_ids)
        for ledger_name in ("object_ledgers", "content_ledgers"):
            ledger = manifest[ledger_name]
            if (
                len(ledger) != len(expected_ids)
                or {item["component_id"] for item in ledger} != expected_ids
                or any(not _is_digest(item["digest"]) for item in ledger)
            ):
                raise ValueError
        seeds = {
            (item["component_id"], item["makerspace_id"], item["state"])
            for item in manifest["not_restored_seeds"]
        }
        expected_seeds = {
            (item["component_id"], item["makerspace_id"], "pending")
            for item in slices
        }
        if (
            len(manifest["not_restored_seeds"]) != len(expected_seeds)
            or seeds != expected_seeds
            or not _is_digest(manifest["user_closure_digest"])
        ):
            raise ValueError
        validate_reservation_manifest(manifest, components)
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupBuildError("The outer archive manifest structure is invalid.") from exc


def _is_digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
