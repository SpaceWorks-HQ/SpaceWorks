from copy import deepcopy

import pytest
from django.apps import apps

from apps.encryption.crypto import encrypt
from apps.encryption.registry import fields_for
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_pii import (
    ENCRYPTED,
    verify_ciphertext_aad_identities,
)
from apps.tenant_migration.tenant_dump_raw import mapped_raw_digest


def _rows():
    makerspace = apps.get_model("makerspaces.Makerspace")
    request = apps.get_model("hardware_requests.HardwareRequest")
    return {
        makerspace._meta.label: ({makerspace._meta.pk.attname: 71},),
        request._meta.label: ({request._meta.pk.attname: 811},),
    }


def test_encrypted_aad_identity_accepts_exact_source_primary_keys():
    source = _rows()
    verify_ciphertext_aad_identities(source, deepcopy(source), 71, mode=ENCRYPTED)


@pytest.mark.parametrize("identity", ("makerspace", "ciphertext_row"))
def test_encrypted_aad_identity_refuses_any_primary_key_remap(identity):
    source = _rows()
    projected = deepcopy(source)
    label = (
        "makerspaces.Makerspace"
        if identity == "makerspace"
        else "hardware_requests.HardwareRequest"
    )
    pk_name = apps.get_model(label)._meta.pk.attname
    projected[label][0][pk_name] += 1

    with pytest.raises(TenantDumpVerificationError, match="primary key was remapped"):
        verify_ciphertext_aad_identities(source, projected, 71, mode=ENCRYPTED)


def test_ciphertext_transport_digest_is_byte_identical_across_projection_shapes():
    request = apps.get_model("hardware_requests.HardwareRequest")
    mapped = fields_for(request)
    row = {request._meta.pk.attname: 812}
    for index, item in enumerate(mapped):
        field = request._meta.get_field(item.field_name)
        row[field.attname] = encrypt(
            f"ciphertext-{index}".encode(),
            b"d" * 32,
            key_version=4,
            makerspace_id=71,
            table=request._meta.db_table,
            pk=812,
            field=item.field_name,
        )
    source = {request._meta.label: (row,)}
    scratch = deepcopy(source)
    restored_dump = deepcopy(scratch)

    assert mapped_raw_digest(source) == mapped_raw_digest(scratch)
    assert mapped_raw_digest(source) == mapped_raw_digest(restored_dump)
    for item in mapped:
        name = request._meta.get_field(item.field_name).attname
        assert source[request._meta.label][0][name].encode() == restored_dump[
            request._meta.label
        ][0][name].encode()
