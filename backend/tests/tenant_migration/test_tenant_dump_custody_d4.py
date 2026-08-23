from types import SimpleNamespace

import pytest
from django.apps import apps
from django.test import override_settings

from apps.backup.recipients_bech32 import convert_bits, encode
from apps.encryption.crypto import encrypt
from apps.encryption.registry import fields_for
from apps.tenant_migration.tenant_dump_dek_helper import age_command
from apps.tenant_migration.tenant_dump_envelope import (
    TENANT_DEKS_MEMBER,
    build_tenant_content_ledger,
    outer_age_command,
)
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_manifest import verify_envelope_custody_manifest
from apps.tenant_migration.tenant_dump_pii import PLAINTEXT, scan_mapped_pii
from apps.tenant_migration.tenant_dump_recipients import recipient_sets


def _recipient(seed):
    return encode("age", convert_bits(bytes([seed]) * 32, 8, 5, pad=True))


def _age_recipients(command):
    return tuple(command[index + 1] for index, value in enumerate(command) if value == "-r")


@pytest.mark.parametrize("superadmin_access", (False, True))
def test_actual_age_arguments_keep_outer_and_tenant_dek_recipients_separate(
    superadmin_access, tmp_path
):
    tenant_one, tenant_two, platform = _recipient(41), _recipient(42), _recipient(43)
    capture = SimpleNamespace(superadmin_access_at_decision=superadmin_access)
    frozen = [
        {"public_recipient": tenant_one},
        {"public_recipient": tenant_two},
    ]

    with override_settings(BACKUP_AGE_RECIPIENT=platform):
        selected = recipient_sets(capture, frozen)

    inner_command = age_command(selected.tenant_dek_recipients)
    outer_command = outer_age_command(
        selected.outer_recipients, tmp_path / "outer.age"
    )
    assert _age_recipients(inner_command) == (tenant_one, tenant_two)
    assert platform not in _age_recipients(inner_command)
    assert _age_recipients(outer_command) == (
        (tenant_one, tenant_two, platform)
        if superadmin_access
        else (tenant_one, tenant_two)
    )


def test_plaintext_content_ledger_declares_absent_tenant_dek_member(tmp_path):
    (tmp_path / "database.dump").write_bytes(b"sanitized dump")

    contents = build_tenant_content_ledger(tmp_path, source_pii_mode=PLAINTEXT)

    key_entry = next(item for item in contents if item["path"] == TENANT_DEKS_MEMBER)
    assert key_entry == {"path": TENANT_DEKS_MEMBER, "present": False}
    assert not (tmp_path / TENANT_DEKS_MEMBER).exists()

    capture = SimpleNamespace(source_encryption_mode=False, source_makerspace_id=71)
    manifest = {
        "source_pii_mode": PLAINTEXT,
        "source": {"source_pii_mode": PLAINTEXT},
        "encryption": {
            "source_pii_mode": PLAINTEXT,
            "mapped_column_findings": {
                "mapped_rows": 1,
                "mapped_values": 1,
                "empty_values": 0,
                "envelope_values": 0,
                "plaintext_values": 1,
            },
            "retained_key_inventory": [],
            "tenant_dek_envelope": {
                "path": TENANT_DEKS_MEMBER,
                "present": False,
            },
        },
        "contents": contents,
    }
    assert verify_envelope_custody_manifest(capture, manifest) is True


def test_plaintext_scan_refuses_a_mapped_ciphertext_envelope():
    model = apps.get_model("hardware_requests.HardwareRequest")
    mapped = tuple(fields_for(model))
    assert mapped
    row = {
        model._meta.get_field(item.field_name).attname: "plaintext"
        for item in mapped
    }
    first = model._meta.get_field(mapped[0].field_name).attname
    row[first] = encrypt(
        b"unexpected ciphertext",
        b"d" * 32,
        key_version=1,
        makerspace_id=71,
        table=model._meta.db_table,
        pk=811,
        field=mapped[0].field_name,
    )

    with pytest.raises(TenantDumpVerificationError, match="ciphertext envelope"):
        scan_mapped_pii({model._meta.label: (row,)}, PLAINTEXT)
