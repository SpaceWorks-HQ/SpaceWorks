import pytest

from apps.makerspaces.capabilities import default_enabled_features, prune_features, validate_capabilities
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import apply_profile
from apps.makerspaces.module_registry import core_module_keys
from apps.makerspaces.platform import bootstrap_payload, feature_enabled
from tests.modules.family_helpers import account, family_space

pytestmark = pytest.mark.django_db


def test_loan_master_switch_has_no_uninstall_or_child_toggle_dependency():
    modules = core_module_keys()
    features, _ = prune_features(default_enabled_features(), modules)
    features.remove("loans.enabled")
    result_modules, result_features = validate_capabilities(sorted(modules), features)
    assert modules <= set(result_modules)
    assert "inventory.self_checkout" in result_features
    space = Makerspace.objects.create(name="Independent loan switch", slug="independent-loan-switch",
        enabled_modules=result_modules, enabled_features=result_features)
    assert not feature_enabled(space, "inventory.self_checkout")
    assert feature_enabled(space, "charges.loans")
    payload = bootstrap_payload(space)
    assert "staff_inventory" not in payload["workflows"]
    assert "staff_requests" not in payload["workflows"]


def test_loan_visibility_preserves_retained_loan_policies_and_payment_capabilities():
    from apps.payments.availability import charge_tracking_enabled

    space = family_space("retained-loan-money", "payments")
    space.enabled_features.extend(["payments.loans", "loans.renewals", "loans.limits"])
    space.save(update_fields=["enabled_features"])
    assert not feature_enabled(space, "loans.enabled")
    assert charge_tracking_enabled(space, "loans")
    assert feature_enabled(space, "payments.loans")
    assert feature_enabled(space, "loans.renewals")
    assert feature_enabled(space, "loans.limits")


def test_minimal_profile_audits_publication_even_when_modules_do_not_change():
    from apps.audit.models import AuditLog

    space = family_space("minimal-publication", loans=True)
    actor = account("minimal-profile-actor", staff=True)
    apply_profile(space, "minimal", actor)
    space.refresh_from_db()
    assert space.public_inventory_enabled is False and space.public_site_enabled is False
    entry = AuditLog.objects.get(makerspace=space, action="makerspace.publication_changed")
    assert entry.actor == actor and entry.meta["after"] == {"site": False, "catalogue": False}
    apply_profile(space, "minimal", actor)
    assert AuditLog.objects.filter(makerspace=space, action="makerspace.publication_changed").count() == 1


def test_publication_fields_have_reviewed_export_and_portable_authority():
    from apps.data_export.classification import EXPORTED_MODEL_FIELDS
    from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
    from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
    from apps.tenant_migration.tenant_dump_types import AuthorityDisposition

    for field in ("public_site_enabled", "public_landing_page"):
        assert field in EXPORTED_MODEL_FIELDS["makerspaces.Makerspace"].split()
        assert field in FIRST_PARTY_FIELD_NAMES["makerspaces.Makerspace"]
        assert AUTHORITY_FIELD_OVERRIDES[("makerspaces.Makerspace", field)].dispositions == (AuthorityDisposition.PRESERVE,)


def test_publication_settings_validate_scope_and_emit_audit_rows():
    from apps.audit.models import AuditLog
    from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
    from tests.modules.family_helpers import client

    space, other = family_space("publication-own"), family_space("publication-other")
    actor = account("publication-manager")
    role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    MakerspaceMembership.objects.create(makerspace=space, user=actor, status="active", assigned_role=role)
    api = client(actor)
    url = f"/api/v1/admin/makerspaces/{space.pk}"
    patch = {"public_site_enabled": False, "public_landing_page": "bookings"}
    assert api.patch(f"/api/v1/admin/makerspaces/{other.pk}", patch, format="json").status_code == 404
    assert api.patch(url, {"public_landing_page": "unknown"}, format="json").status_code == 400
    result = api.patch(url, patch, format="json")
    assert result.status_code == 200, result.data
    space.refresh_from_db()
    assert space.public_site_enabled is False and space.public_landing_page == "bookings"
    row = AuditLog.objects.get(makerspace=space, actor=actor, action="makerspace.updated")
    assert set(row.meta["fields"]) == set(patch)
