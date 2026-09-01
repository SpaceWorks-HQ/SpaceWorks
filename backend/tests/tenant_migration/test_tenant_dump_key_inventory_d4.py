from dataclasses import replace

import pytest

from apps.backup.dek_rewrap import StagedDekRow
from apps.backup.digests import sha256_bytes
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_key_inventory import (
    manifest_key_inventory,
    require_exact_retained_key_set,
    retained_key_rows,
)
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_pii import ENCRYPTED, PLAINTEXT
from apps.tenant_migration.tenant_dump_types import ModelDisposition


def _row(row_id, version, status="active", wrapped=None):
    wrapped = wrapped or f"wrapped-{row_id}-{version}".encode()
    return StagedDekRow(
        row_identity=row_id,
        makerspace_id=91,
        version=version,
        status=status,
        broker_backend="local",
        broker_key_id="source-master-key",
        wrapped_dek=wrapped,
        wrapped_dek_sha256=sha256_bytes(wrapped),
    )


def test_plaintext_mode_has_an_empty_non_secret_key_inventory():
    assert retained_key_rows((_row(3, 3, "disabled"),), mode=PLAINTEXT) == ()
    assert manifest_key_inventory(()) == []


def test_source_key_rows_and_derived_indexes_never_enter_database_dump():
    labels = {
        "encryption.MakerspaceEncryptionKey",
        "encryption.PiiBlindIndex",
        "encryption.SearchKeyGeneration",
    }
    assert all(
        FIRST_PARTY_MODEL_RULES[label].disposition is ModelDisposition.DROP
        for label in labels
    )


@pytest.mark.parametrize("fault", ("missing", "duplicate", "extra", "disabled", "substituted"))
def test_exact_retained_key_set_refuses_every_substitution_class(fault):
    active = _row(1, 1)
    rotated = _row(2, 2, "rotated")
    disabled = _row(3, 3, "disabled")
    source = (active, rotated, disabled)
    candidate = (active, rotated)
    if fault == "missing":
        candidate = (active,)
    elif fault == "duplicate":
        candidate = (active, active, rotated)
    elif fault == "extra":
        candidate = (*candidate, _row(4, 4))
    elif fault == "disabled":
        candidate = (*candidate, replace(disabled, status="active"))
    elif fault == "substituted":
        changed = b"live-source-substitution"
        candidate = (
            replace(
                active,
                wrapped_dek=changed,
                wrapped_dek_sha256=sha256_bytes(changed),
            ),
            rotated,
        )

    with pytest.raises(TenantDumpVerificationError):
        require_exact_retained_key_set(source, candidate)


def test_encrypted_mode_retains_only_active_and_rotated_rows():
    source = (_row(1, 1), _row(2, 2, "rotated"), _row(3, 3, "disabled"))
    retained = retained_key_rows(source, mode=ENCRYPTED)

    assert [row.status for row in retained] == ["active", "rotated"]
    inventory = manifest_key_inventory(retained)
    assert all("wrapped_dek" not in item and "dek" not in item for item in inventory)
