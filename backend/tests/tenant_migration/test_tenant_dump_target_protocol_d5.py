from copy import deepcopy
from io import BytesIO
import json
import struct

import pytest

from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_target_helper import _stream_records
from apps.tenant_migration.tenant_dump_target_protocol import (
    INSTALL_PROTOCOL,
    decode_request,
    encode_install_request,
)
from tests.tenant_migration.tenant_dump_d5_helpers import (
    key_inventory,
    target_identity,
)


def _request(makerspace_id=9, *, inventory=None):
    return encode_install_request(
        identities=(target_identity("/identity/tenant.age", 11),),
        envelope_path="/artifact/keys/tenant-deks.age",
        makerspace_id=makerspace_id,
        inventory=key_inventory(9) if inventory is None else inventory,
    )


@pytest.mark.parametrize("makerspace_id", (0, -7, False, True))
def test_helper_owner_identity_requires_positive_non_boolean_integer(makerspace_id):
    with pytest.raises(TenantDumpTargetError) as caught:
        _request(makerspace_id)

    assert caught.value.code == "key_inventory"


@pytest.mark.parametrize("field", ("source_key_row_id", "version"))
@pytest.mark.parametrize("value", (0, -1, False, True))
def test_helper_key_identities_require_positive_non_boolean_integers(field, value):
    inventory = key_inventory(9)
    inventory[0][field] = value

    with pytest.raises(TenantDumpTargetError) as caught:
        _request(inventory=inventory)

    assert caught.value.code == "key_inventory"


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_field",
        "extra_field",
        "duplicate_row",
        "duplicate_version",
        "invalid_status",
        "invalid_backend",
        "invalid_digest",
        "no_active",
        "two_active",
    ),
)
def test_manifest_key_inventory_shape_is_exact_and_has_one_active(mutation):
    inventory = key_inventory(9)
    if mutation == "missing_field":
        inventory[0].pop("source_broker_key_id")
    elif mutation == "extra_field":
        inventory[0]["dek"] = "forbidden"
    elif mutation == "duplicate_row":
        inventory[1]["source_key_row_id"] = inventory[0]["source_key_row_id"]
    elif mutation == "duplicate_version":
        inventory[1]["version"] = inventory[0]["version"]
    elif mutation == "invalid_status":
        inventory[0]["status"] = "disabled"
    elif mutation == "invalid_backend":
        inventory[0]["source_broker_backend"] = "target-local"
    elif mutation == "invalid_digest":
        inventory[0]["source_wrapped_dek_sha256"] = "A" * 64
    elif mutation == "no_active":
        inventory[1]["status"] = "rotated"
    else:
        inventory[0]["status"] = "active"

    with pytest.raises(TenantDumpTargetError) as caught:
        _request(inventory=inventory)

    assert caught.value.code == "key_inventory"


def test_parent_protocol_contains_paths_and_public_inventory_but_no_secret_material():
    payload = _request()
    protocol, request = decode_request(payload)

    assert protocol == INSTALL_PROTOCOL
    assert request["makerspace_id"] == 9
    assert request["identity_paths"] == ("/identity/tenant.age",)
    assert request["inventory"] == key_inventory(9)
    forbidden_keys = {"dek", "dek_base64", "wrapped_dek", "plaintext_dek"}
    assert all(not (forbidden_keys & set(row)) for row in request["inventory"])
    assert b"AGE-SECRET-KEY-" not in payload


def _record(owner, version, status, dek=b"d" * 32):
    encoded_status = status.encode("ascii")
    return b"".join(
        (
            struct.pack(">QI", owner, version),
            struct.pack(">H", len(encoded_status)),
            encoded_status,
            struct.pack(">H", len(dek)),
            dek,
        )
    )


def _expected():
    return key_inventory(9, versions=((3, "rotated"), (7, "active")))


@pytest.mark.parametrize(
    "mutation",
    ("owner", "version", "status", "short_dek", "truncated"),
)
def test_decrypted_key_records_must_match_the_manifest_inventory(mutation):
    expected = _expected()
    owner, version, status, dek = 9, 3, "rotated", b"d" * 32
    if mutation == "owner":
        owner = 10
    elif mutation == "version":
        version = 4
    elif mutation == "status":
        status = "active"
    elif mutation == "short_dek":
        dek = b"d" * 31
    payload = _record(owner, version, status, dek)
    if mutation == "truncated":
        payload = payload[:-1]

    with pytest.raises((TenantDumpTargetError, ValueError)):
        list(_stream_records(BytesIO(payload), expected[:1]))


def test_protocol_decoder_refuses_unknown_fields_instead_of_ignoring_them():
    value = json.loads(_request())
    value["plaintext_dek"] = "must-not-be-tolerated"

    with pytest.raises(TenantDumpTargetError) as caught:
        decode_request(json.dumps(value).encode())

    assert caught.value.code == "helper_protocol"


def test_protocol_round_trip_does_not_mutate_the_frozen_inventory():
    inventory = key_inventory(9)
    original = deepcopy(inventory)

    decode_request(_request(inventory=inventory))

    assert inventory == original
