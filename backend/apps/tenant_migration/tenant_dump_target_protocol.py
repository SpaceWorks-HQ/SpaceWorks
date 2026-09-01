"""Secret-free parent protocol for target-side Lane D helper operations."""

import json

from .tenant_dump_errors import TenantDumpTargetError


INSTALL_PROTOCOL = "spaceworks-lane-d-target-dek-install-v1"
CHALLENGE_PROTOCOL = "spaceworks-lane-d-target-recipient-proof-v1"


def encode_install_request(*, identities, envelope_path, makerspace_id, inventory):
    rows = _validated_inventory(inventory, makerspace_id)
    request = {
        "protocol": INSTALL_PROTOCOL,
        "identity_paths": [str(item.path) for item in identities],
        "envelope_path": str(envelope_path),
        "makerspace_id": makerspace_id,
        "inventory": rows,
    }
    return _encode(request)


def encode_challenge_request(*, identity, ciphertext):
    if not isinstance(ciphertext, str) or not ciphertext:
        _refuse("The target recipient challenge is invalid.", "challenge_invalid")
    return _encode(
        {
            "protocol": CHALLENGE_PROTOCOL,
            "identity_path": str(identity.path),
            "ciphertext": ciphertext,
        }
    )


def decode_request(payload):
    try:
        value = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        _refuse("The target helper request is invalid.", "helper_protocol")
    protocol = value.get("protocol") if isinstance(value, dict) else None
    if protocol == INSTALL_PROTOCOL:
        return protocol, _decode_install(value)
    if protocol == CHALLENGE_PROTOCOL:
        return protocol, _decode_challenge(value)
    _refuse("The target helper request is invalid.", "helper_protocol")


def _decode_install(value):
    try:
        makerspace_id = value["makerspace_id"]
        paths = tuple(value["identity_paths"])
        envelope_path = value["envelope_path"]
        inventory = _validated_inventory(value["inventory"], makerspace_id)
    except (KeyError, TypeError, ValueError):
        _refuse("The target DEK helper request is invalid.", "helper_protocol")
    if (
        set(value) != {
            "protocol",
            "identity_paths",
            "envelope_path",
            "makerspace_id",
            "inventory",
        }
        or not paths
        or len(paths) != len(set(paths))
        or any(not isinstance(path, str) or not path for path in paths)
        or not isinstance(envelope_path, str)
        or not envelope_path
    ):
        _refuse("The target DEK helper request is invalid.", "helper_protocol")
    return {
        "identity_paths": paths,
        "envelope_path": envelope_path,
        "makerspace_id": makerspace_id,
        "inventory": inventory,
    }


def _decode_challenge(value):
    if (
        set(value) != {"protocol", "identity_path", "ciphertext"}
        or not isinstance(value.get("identity_path"), str)
        or not value["identity_path"]
        or not isinstance(value.get("ciphertext"), str)
        or not value["ciphertext"]
    ):
        _refuse("The target recipient helper request is invalid.", "helper_protocol")
    return {
        "identity_path": value["identity_path"],
        "ciphertext": value["ciphertext"],
    }


def _validated_inventory(inventory, makerspace_id):
    required = {
        "source_key_row_id",
        "makerspace_id",
        "version",
        "status",
        "source_broker_backend",
        "source_broker_key_id",
        "source_wrapped_dek_sha256",
    }
    if type(makerspace_id) is not int or makerspace_id <= 0:
        _refuse("The target DEK inventory owner is invalid.", "key_inventory")
    normalized = []
    seen_rows = set()
    seen_versions = set()
    try:
        for item in inventory:
            if not isinstance(item, dict) or set(item) != required:
                raise ValueError
            row_id = item["source_key_row_id"]
            version = item["version"]
            status = item["status"]
            digest = item["source_wrapped_dek_sha256"]
            if (
                type(row_id) is not int
                or row_id <= 0
                or type(version) is not int
                or version <= 0
                or item["makerspace_id"] != makerspace_id
                or status not in {"active", "rotated"}
                or item["source_broker_backend"] not in {"local", "aws_kms"}
                or not isinstance(item["source_broker_key_id"], str)
                or not item["source_broker_key_id"]
                or not _is_sha256(digest)
                or row_id in seen_rows
                or version in seen_versions
            ):
                raise ValueError
            seen_rows.add(row_id)
            seen_versions.add(version)
            normalized.append(dict(item))
    except (TypeError, ValueError):
        _refuse("The target DEK inventory is invalid.", "key_inventory")
    if not normalized or sum(row["status"] == "active" for row in normalized) != 1:
        _refuse("The target must receive exactly one active DEK.", "key_inventory")
    return sorted(normalized, key=lambda row: row["version"])


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _refuse(message, code):
    raise TenantDumpTargetError(message, code=code)
