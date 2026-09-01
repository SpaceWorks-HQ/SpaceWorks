from contextlib import ExitStack
from copy import deepcopy
import hashlib
from unittest import mock

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model

from apps.backup.raw_projection import no_decrypt_guard, raw_records
from apps.hardware_requests.models import HardwareRequest
from apps.machines.models import MachineType
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.tenant_dump_catalog import TenantDumpCatalogError
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError
from apps.tenant_migration.tenant_dump_machine_types import resolve_machine_types
from apps.tenant_migration.tenant_dump_objects import package_staged_objects
from apps.tenant_migration.tenant_dump_raw import (
    RAW_COLUMN_ALLOWLISTS,
    mapped_raw_digest,
    sanitize_record,
    validate_raw_column_allowlists,
)
from tests.encryption.conftest import enabled_encryption


pytestmark = pytest.mark.django_db


def _raw_type(machine_type):
    return MachineType.objects.filter(pk=machine_type.pk).values(
        *(field.attname for field in MachineType._meta.concrete_fields)
    ).get()


def test_raw_column_allowlist_equals_every_catalog_concrete_field():
    validate_raw_column_allowlists()
    actual = {
        model._meta.label: frozenset(
            field.attname for field in model._meta.concrete_fields
        )
        for model in apps.get_models(include_auto_created=True)
        if not model._meta.proxy
    }
    assert RAW_COLUMN_ALLOWLISTS == actual


def test_raw_column_allowlist_drift_fails_closed():
    changed = deepcopy(RAW_COLUMN_ALLOWLISTS)
    changed["accounts.User"] = changed["accounts.User"] - {"email"}
    with pytest.raises(TenantDumpCatalogError, match="raw-column allowlist drifted"):
        validate_raw_column_allowlists(allowlists=changed)


def test_machine_type_builtin_fingerprint_mismatch_refuses():
    built_in = MachineType.objects.filter(makerspace__isnull=True).first()
    assert built_in is not None
    source = _raw_type(built_in)
    source["name"] = source["name"] + " altered"

    with pytest.raises(TenantDumpVerificationError, match="definition differs"):
        resolve_machine_types("default", (source,), MachineType)


def test_tenant_custom_machine_type_travels_instead_of_resolving():
    makerspace = Makerspace.objects.create(
        name="D2 custom type lab", slug="d2-custom-type-lab"
    )
    custom = MachineType.objects.create(
        makerspace=makerspace,
        slug="lane-d-custom",
        name="Lane D custom",
    )

    resolved, travelling = resolve_machine_types(
        "default", (_raw_type(custom),), MachineType
    )

    assert resolved == {}
    assert travelling[0]["id"] == custom.pk


def test_sanitization_preserves_encrypted_raw_digest_without_dek_access():
    with enabled_encryption():
        makerspace = Makerspace.objects.create(
            name="D2 encrypted lab", slug="d2-encrypted-lab"
        )
        requester = get_user_model().objects.create_user(
            username="d2-digest-requester"
        )
        request = HardwareRequest.objects.create(
            makerspace=makerspace,
            requester=requester,
            requester_username=requester.username,
            requester_name="Ciphertext must remain raw",
            requested_for="D2 digest fixture",
        )
        source = raw_records(
            HardwareRequest.objects.filter(pk=request.pk), HardwareRequest
        )[0]
        targets = (
            "apps.encryption.crypto.decrypt",
            "apps.encryption.crypto.decrypt_with_key_loader",
            "apps.encryption.services.get_dek",
            "apps.encryption.services.unwrap_dek",
            "apps.encryption.mappers.decrypt_with_key_loader",
            "apps.encryption.mappers.get_dek",
        )
        with ExitStack() as stack, no_decrypt_guard():
            spies = [
                stack.enter_context(
                    mock.patch(target, side_effect=AssertionError(target))
                )
                for target in targets
            ]
            sanitized = sanitize_record(HardwareRequest, source)

    inserted_shape = {
        field.attname: sanitized.values[field.column]
        for field in HardwareRequest._meta.concrete_fields
    }
    label = HardwareRequest._meta.label
    assert mapped_raw_digest({label: (source,)}) == mapped_raw_digest(
        {label: (inserted_shape,)}
    )
    assert all(spy.call_count == 0 for spy in spies)


def test_objects_are_packaged_from_immutable_staging_with_sha256(tmp_path):
    staging = tmp_path / "staging"
    bundle = tmp_path / "bundle"
    member = staging / "objects" / "private" / "captured"
    member.parent.mkdir(parents=True)
    payload = b"immutable Lane D object bytes"
    member.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    manifest = package_staged_objects(
        staging,
        bundle,
        (
            {
                "bucket_kind": "private",
                "member_path": "objects/private/captured",
                "source_key": "evidence/source-key.jpg",
                "version_id": "version-7",
                "size": len(payload),
                "content_type": "image/jpeg",
                "sha256": digest,
                "etag": "not-a-content-digest",
            },
        ),
    )

    assert manifest[0]["original_key"] == "evidence/source-key.jpg"
    assert manifest[0]["sha256"] == digest
    assert manifest[0]["version_id"] == "version-7"
    assert "etag" not in manifest[0]
    assert (bundle / manifest[0]["member_path"]).read_bytes() == payload
