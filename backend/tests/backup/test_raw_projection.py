import json
from contextlib import ExitStack
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import serializers

from apps.backup import tenant_projection
from apps.backup.archive_payload import _tenant_payload
from apps.backup.raw_projection import RawProjectionViolation, no_decrypt_guard
from apps.backup.tenant_projection import project_raw_dataset
from apps.encryption import crypto, mappers, services
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace
from tests.encryption.conftest import enabled_encryption


pytestmark = pytest.mark.django_db


def make_request():
    space = Makerspace.objects.create(name="Raw archive", slug="raw-archive")
    user = get_user_model().objects.create_user(username="raw-requester")
    request = HardwareRequest.objects.create(
        makerspace=space,
        requester=user,
        requester_username=user.username,
        requester_name="Raw Fixture Name",
        requester_contact_email="raw@example.test",
        requester_contact_phone="12345",
        requested_for="fixture compatibility",
    )
    return space, request


def test_tenant_fixture_bytes_match_the_previous_producer_when_encryption_is_off(
    settings, tmp_path
):
    settings.PII_ENCRYPTION_ENABLED = False
    space, request = make_request()
    queryset = HardwareRequest.objects.filter(pk=request.pk).order_by("pk")
    previous = json.dumps(
        json.loads(serializers.serialize("json", list(queryset))), sort_keys=True
    )
    makerspace_previous = json.dumps(
        json.loads(serializers.serialize(
            "json", list(Makerspace.objects.filter(pk=space.pk).order_by("pk"))
        )),
        sort_keys=True,
    )

    _tenant_payload(space.pk, tmp_path / "tenant")

    emitted = tmp_path / "tenant" / "hardware_requests_hardwarerequest.json"
    assert emitted.read_text(encoding="utf-8") == previous
    assert (
        tmp_path / "tenant" / "makerspaces_makerspace.json"
    ).read_text(encoding="utf-8") == makerspace_previous
    assert set(json.loads(previous)[0]) == {"model", "pk", "fields"}


def test_encrypted_tenant_projection_never_loads_a_dek_and_emits_ciphertext(tmp_path):
    with enabled_encryption():
        space, request = make_request()
        mapped_names = (
            "requester_username",
            "requester_name",
            "requester_contact_email",
            "requester_contact_phone",
        )
        stored = HardwareRequest.objects.filter(pk=request.pk).values(*mapped_names).get()
        assert all(value.startswith("pii:gcm:v1:") for value in stored.values())
        assert request.__dict__["requester_name"] == "Raw Fixture Name"
        assert request.__dict__["_pii_plain_values"]["requester_name"] == "Raw Fixture Name"

        targets = (
            "apps.encryption.crypto.decrypt",
            "apps.encryption.crypto.decrypt_with_key_loader",
            "apps.encryption.services.get_dek",
            "apps.encryption.services.unwrap_dek",
            "apps.encryption.mappers.decrypt_with_key_loader",
            "apps.encryption.mappers.get_dek",
        )
        with ExitStack() as stack:
            spies = [
                stack.enter_context(mock.patch(target, side_effect=AssertionError(target)))
                for target in targets
            ]
            _tenant_payload(space.pk, tmp_path / "tenant")

        assert all(spy.call_count == 0 for spy in spies)
        fields = json.loads(
            (tmp_path / "tenant" / "hardware_requests_hardwarerequest.json").read_text(
                encoding="utf-8"
            )
        )[0]["fields"]
        assert {name: fields[name] for name in mapped_names} == stored


@pytest.mark.parametrize(
    ("encryption_enabled", "dual_read", "seed_plain_cache"),
    ((True, False, True), (True, True, False), (False, False, False)),
)
def test_guard_rejects_mapped_access_across_every_decrypt_bypass(
    settings, encryption_enabled, dual_read, seed_plain_cache
):
    settings.PII_ENCRYPTION_ENABLED = encryption_enabled
    settings.PII_ENCRYPTION_DUAL_READ = dual_read
    row = HardwareRequest(requester_name="raw ciphertext placeholder")
    if seed_plain_cache:
        row.__dict__["_pii_plain_values"] = {"requester_name": "cached plaintext"}

    with no_decrypt_guard(), pytest.raises(
        RawProjectionViolation, match="requester_name"
    ):
        _ = row.requester_name


def test_guard_patches_defining_functions_mapper_aliases_and_legacy_paths():
    row = HardwareRequest(requester_name="value")
    forbidden_calls = (
        lambda: crypto.decrypt("value", b"key", makerspace_id=1, table="t", pk=1, field="f"),
        lambda: crypto.decrypt_with_key_loader(
            "value",
            makerspace_id=1,
            table="t",
            pk=1,
            field="f",
            load_dek=lambda version: b"key",
        ),
        lambda: services.get_dek(1, 1),
        lambda: services.unwrap_dek(None),
        lambda: mappers.decrypt_with_key_loader(
            "value",
            makerspace_id=1,
            table="t",
            pk=1,
            field="f",
            load_dek=lambda version: b"key",
        ),
        lambda: mappers.get_dek(1, 1),
        lambda: serializers.serialize("json", []),
        lambda: tenant_projection.project_dataset("unused", [], 1),
        lambda: row.save(),
    )

    with mock.patch.object(tenant_projection, "project_dataset", return_value=None) as legacy:
        with no_decrypt_guard():
            for operation in forbidden_calls:
                with pytest.raises(RawProjectionViolation):
                    operation()
    assert legacy.call_count == 0


def test_raw_producer_rejects_model_instances():
    row = HardwareRequest(pk=1, requester_name="plaintext cache risk")

    with pytest.raises(RawProjectionViolation, match="raw records only"):
        project_raw_dataset(
            "hardware_requests.HardwareRequest", HardwareRequest, [row], 1
        )
