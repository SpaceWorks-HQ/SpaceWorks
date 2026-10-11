"""RBAC, module/version refusals, saved profiles and creation rollback."""
from copy import deepcopy
import pytest

from apps.audit.models import AuditLog
from apps.data_export.classification import OMITTED_MODELS
from apps.makerspaces.models import Makerspace, MakerspaceRole, SpacePackProfile
from apps.makerspaces.module_registry import core_module_keys
from apps.makerspaces.space_pack_export import export_pack
from apps.makerspaces.space_pack_format import seal
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES, PROJECTED_MODEL_LABELS
from apps.tenant_migration.tenant_dump_types import ModelDisposition
from .space_pack_helpers import client, person, seed_configuration, space

pytestmark = pytest.mark.django_db(transaction=True)


def test_space_manager_own_scope_and_suspended_accounts_are_refused():
    row, actor = space("pack-api")
    other, _ = space("pack-other")
    url = f"/api/v1/admin/makerspace/{row.pk}/space-pack"
    assert client().get(url).status_code == 401
    assert client(actor).get(url).status_code == 200
    assert client(actor).get(f"/api/v1/admin/makerspace/{other.pk}/space-pack").status_code == 404
    assert client(person("pack-outsider")).get(url).status_code == 404
    actor.access_status = "suspended"
    actor.save(update_fields=["access_status"])
    assert client(actor).get(url).status_code == 403


def test_hidden_space_is_not_available_to_global_superadmin():
    row, actor = space("pack-hidden")
    row.superadmin_access_enabled = False
    row.save(update_fields=["superadmin_access_enabled"])
    url = f"/api/v1/admin/makerspace/{row.pk}/space-pack"
    assert client(person("pack-hidden-super", superadmin=True)).get(url).status_code == 404
    assert client(actor).get(url).status_code == 200


def test_feature_and_module_off_answer_400_not_404():
    row, actor = space("pack-gates")
    url = f"/api/v1/admin/makerspace/{row.pk}/space-pack"
    row.enabled_features = []
    row.save(update_fields=["enabled_features"])
    assert client(actor).get(url).status_code == 400
    row.enabled_features = ["packs.import"]
    row.enabled_modules = [key for key in row.enabled_modules if key != "staff_admin"]
    row.save(update_fields=["enabled_features", "enabled_modules"])
    assert client(actor).get(url).status_code == 400


def test_modules_remain_superadmin_only_and_edition_is_not_a_pack_field():
    row, actor = space("pack-module-permission")
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["modules"] = sorted(core_module_keys())
    config["features"] = ["packs.import"]
    url = f"/api/v1/admin/makerspace/{row.pk}/space-pack"
    response = client(actor).post(url, {"pack": seal(config)}, format="json")
    assert response.status_code == 403
    before = AuditLog.objects.count()
    root = person("pack-module-super", superadmin=True)
    preview = client(root).post(url, {"pack": seal(config)}, format="json")
    assert preview.status_code == 200
    applied = client(root).post(url, {"pack": seal(config), "dry_run": False,
        "base_checksum": preview.data["base_checksum"]}, format="json")
    assert applied.status_code == 200
    row.refresh_from_db()
    assert set(row.enabled_modules) == core_module_keys()
    assert AuditLog.objects.count() > before
    config["edition_override"] = "events"
    assert client(root).post(url, {"pack": seal(config)}, format="json").status_code == 400


@pytest.mark.parametrize("protected_name", ["Space Manager", "space manager"])
def test_custom_role_import_enforces_non_escalation_and_protected_roles(protected_name):
    row, actor = space("pack-role-permission")
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["roles"] = [{"name": "Another Manager", "granted_actions": ["manage_makerspace"]}]
    url = f"/api/v1/admin/makerspace/{row.pk}/space-pack"
    assert client(actor).post(url, {"pack": seal(config)}, format="json").status_code == 403
    config["roles"] = [{"name": protected_name, "granted_actions": ["view_inventory"]}]
    assert client(actor).post(url, {"pack": seal(config)}, format="json").status_code == 400
    assert not MakerspaceRole.objects.filter(makerspace=row, name="Another Manager").exists()


def test_unknown_version_and_checksum_refusals_do_not_write():
    row, actor = space("pack-api-version")
    pack = export_pack(actor, row)
    url = f"/api/v1/admin/makerspace/{row.pk}/space-pack"
    count = AuditLog.objects.count()
    pack["version"] = 99
    result = client(actor).post(url, {"pack": pack}, format="json")
    assert result.status_code == 400 and result.data["code"] == "unsupported_pack_version"
    pack["version"] = 1
    pack["checksum"] = "0" * 64
    assert client(actor).post(url, {"pack": pack}, format="json").status_code == 400
    assert AuditLog.objects.count() == count


def test_platform_profiles_are_superadmin_only_paginated_and_not_tenant_dump_data():
    row, actor = space("pack-profiles")
    pack = export_pack(actor, row)
    url = "/api/v1/admin/space-pack-profiles"
    assert client(actor).get(url).status_code == 403
    assert client(actor).post(url, {"name": "Library", "pack": pack}, format="json").status_code == 403
    root = person("pack-profiles-super", superadmin=True)
    response = client(root).post(url, {"name": "Library", "pack": pack}, format="json")
    assert response.status_code == 201
    listing = client(root).get(url)
    assert listing.status_code == 200 and listing.data["count"] == 1
    assert listing.data["results"][0]["pack"] == pack
    assert AuditLog.objects.filter(action="platform.space_pack_profile_saved", actor=root, makerspace__isnull=True).exists()
    label = "makerspaces.SpacePackProfile"
    assert label in OMITTED_MODELS and label not in PROJECTED_MODEL_LABELS
    assert FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.DROP


def test_create_makerspace_applies_saved_profile_in_creation_transaction():
    row, actor = space("pack-creation-source")
    seed_configuration(row, actor)
    pack = export_pack(actor, row)
    root = person("pack-creation-super", superadmin=True)
    profile = client(root).post("/api/v1/admin/space-pack-profiles", {"name": "Workshop", "pack": pack}, format="json")
    assert profile.status_code == 201
    created = client(root).post("/api/v1/admin/makerspaces", {
        "name": "New space", "slug": "pack-created", "public_code": "PKCA", "install_profile_id": profile.data["id"],
    }, format="json")
    assert created.status_code == 201
    target = Makerspace.objects.get(slug="pack-created")
    assert export_pack(root, target) == pack
    missing = client(root).post("/api/v1/admin/makerspaces", {
        "name": "Rolled back", "slug": "pack-absent-profile", "public_code": "PKCB", "install_profile_id": 987654321,
    }, format="json")
    assert missing.status_code == 404
    assert not Makerspace.objects.filter(slug="pack-absent-profile").exists()
    assert SpacePackProfile.objects.count() == 1


@pytest.mark.parametrize("version", [True, "1", 2])
def test_http_protocol_does_not_coerce_unknown_version_types(version):
    import hashlib
    from apps.makerspaces.space_pack_format import canonical
    row, actor = space(f"pack-version-type-{version}")
    pack = export_pack(actor, row)
    pack["version"] = version
    unsigned = {key: pack[key] for key in ("format", "version", "configuration")}
    pack["checksum"] = hashlib.sha256(canonical(unsigned)).hexdigest()
    response = client(actor).post(f"/api/v1/admin/makerspace/{row.pk}/space-pack", {"pack": pack}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "unsupported_pack_version"


def test_apply_service_refuses_a_frozen_tenant_before_any_write():
    from apps.makerspaces.space_pack_services import apply_pack, preview_pack
    from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
    from apps.tenant_migration.models_source_gate import SourceMigrationGate
    from django.utils import timezone
    from datetime import timedelta
    row, actor = space("pack-frozen")
    pack = export_pack(actor, row)
    preview = preview_pack(actor, row, pack)
    SourceMigrationGate.objects.create(makerspace=row, state=SourceMigrationGate.State.QUIESCED,
        owner_id=SourceMigrationGate.new_owner_id(), heartbeat_at=timezone.now(),
        lease_expires_at=timezone.now() + timedelta(hours=1))
    before = AuditLog.objects.count()
    with pytest.raises(SourceMigrationGateClosed):
        apply_pack(actor, row, pack, base_checksum=preview["base_checksum"])
    assert AuditLog.objects.count() == before


def test_saved_profiles_refuse_missing_references_and_contradictory_policy_aliases():
    row, actor = space("pack-profile-closure")
    seed_configuration(row, actor)
    root = person("pack-profile-closure-root", superadmin=True)
    original = export_pack(actor, row)["configuration"]
    before = AuditLog.objects.count()
    for edit in ("categories", "membership_plans", "loan_policy"):
        config = deepcopy(original)
        if edit == "loan_policy":
            config[edit]["default_loan_days"] += 1
        else:
            config[edit] = []
        response = client(root).post("/api/v1/admin/space-pack-profiles", {
            "name": f"Invalid {edit}", "pack": seal(config),
        }, format="json")
        assert response.status_code == 400
    assert not SpacePackProfile.objects.exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize("field,value", [
    ("voucher_pending_limit", 101), ("voucher_min_tenure_days", 3651),
    ("vouch_expiry_days", 366), ("request_expiry_days", 366),
    ("joining_fee_currency", "u12"),
])
def test_admission_import_keeps_existing_editor_bounds(field, value):
    row, actor = space(f"pack-admission-bounds-{field}")
    seed_configuration(row, actor)
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["admission_policy"][field] = value
    before = AuditLog.objects.count()
    response = client(actor).post(f"/api/v1/admin/makerspace/{row.pk}/space-pack", {"pack": seal(config)}, format="json")
    assert response.status_code == 400
    assert AuditLog.objects.count() == before
