"""Query-free envelope and explicit configuration classification guards."""
import pytest

from apps.data_export.classification import EXPORTED_MODEL_FIELDS, OMITTED_MODELS
from apps.data_export.space_pack_configuration import (
    HOURS_FIELDS, PACK_ONLY_CONFIGURATION_MODELS, SECTIONS, SETTINGS_FIELDS, assert_pack_classification,
)
from apps.encryption.registry import ALL_FIELDS
from apps.makerspaces.space_pack_format import PackError, canonical, open_pack, seal


def test_checksum_is_canonical_and_detects_tampering():
    assert seal({"b": 1, "a": 2}) == seal({"a": 2, "b": 1})
    pack = seal({"a": 1})
    assert open_pack(pack) == {"a": 1}
    pack["configuration"]["a"] = 2
    with pytest.raises(PackError, match="checksum"):
        open_pack(pack)


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_unknown_versions_are_refused_even_with_checksum(version):
    pack = seal({})
    pack["version"] = version
    with pytest.raises(PackError) as error:
        open_pack(pack)
    assert error.value.detail["code"] == "unsupported_pack_version"


@pytest.mark.parametrize("field", ["members", "payments", "evidence", "audit", "edition"])
def test_extra_envelope_fields_cannot_smuggle_tenant_records(field):
    pack = seal({})
    pack[field] = []
    with pytest.raises(PackError):
        open_pack(pack)


def test_pack_projection_is_a_reviewed_subset_of_data_export_without_pii_or_money_models():
    assert_pack_classification()
    labels = {spec.model for spec in SECTIONS.values()}
    assert not any(label.startswith(("accounts.", "payments.", "evidence.", "audit.", "hardware_requests.")) for label in labels)
    forbidden_models = {field.model_label for field in ALL_FIELDS}
    assert not labels & forbidden_models
    fields = {name for spec in SECTIONS.values() for name in spec.fields}
    assert not fields & {"user", "member", "uploaded_by", "created_by", "updated_by", "actor", "object_key", "storage_location", "box", "public_token"}
    assert not any("quantity" in field for field in fields)
    for spec in SECTIONS.values():
        if spec.model in PACK_ONLY_CONFIGURATION_MODELS:
            assert spec.model in OMITTED_MODELS
        else:
            assert set(spec.fields) <= set(EXPORTED_MODEL_FIELDS[spec.model].split())
    assert not set(SETTINGS_FIELDS + HOURS_FIELDS) & {"name", "slug", "public_api_key", "smtp_password", "telegram_group_chat_id", "frontend_domain"}


def test_invalid_json_values_and_oversize_are_refused():
    for value in (float("nan"), float("inf"), object()):
        with pytest.raises(PackError):
            canonical(value)
    with pytest.raises(PackError):
        seal({"body": "x" * (2 * 1024 * 1024)})


def test_non_ascii_checksum_and_invalid_unicode_are_refused():
    pack = seal({})
    pack["checksum"] = "é" * 64
    with pytest.raises(PackError):
        open_pack(pack)
    with pytest.raises(PackError):
        canonical({"text": "\ud800"})
