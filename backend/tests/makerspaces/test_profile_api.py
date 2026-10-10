import copy

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.payments.models import MakerspacePaymentSettings, Payment
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def route(lab):
    return f"/api/v1/admin/makerspace/{lab.pk}/profile"


@pytest.fixture
def profile():
    lab = make_space("profile-lab")
    manager = make_member("profile-manager", lab)
    return lab, manager, authenticated_client(manager)


def test_profile_get_does_not_create_settings_and_works_without_modules(profile):
    lab, _, client = profile
    lab.enabled_modules = []
    lab.save(update_fields=["enabled_modules"])
    response = client.get(route(lab))
    assert response.status_code == 200
    assert response.data["opening_hours"] == {}
    assert response.data["default_currency"] == "usd"
    assert "Asia/Kolkata" in response.data["timezone_choices"]
    assert "IN" in response.data["country_choices"]
    assert not MakerspacePaymentSettings.objects.filter(makerspace=lab).exists()


def test_profile_patch_uses_existing_currency_authority_and_audits_only_fields(profile):
    lab, manager, client = profile
    payment_settings = MakerspacePaymentSettings.objects.create(makerspace=lab, default_currency="eur")
    existing_charge = Payment.objects.create(
        makerspace=lab, member=manager, created_by=manager,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP, subject_id=manager.pk,
        amount="10.00", currency="eur", provider=Payment.Provider.UNCLAIMED,
    )
    hours = {"weekly": {}, "exceptions": {"2026-12-25": []}}
    response = client.patch(route(lab), {
        "timezone": "Asia/Kolkata", "country": "IN",
        "opening_hours": hours, "default_currency": "INR",
    }, format="json")
    assert response.status_code == 200
    lab.refresh_from_db()
    payment_settings.refresh_from_db()
    assert (lab.timezone, lab.country, lab.opening_hours) == ("Asia/Kolkata", "IN", hours)
    assert payment_settings.default_currency == response.data["default_currency"] == "inr"
    entry = AuditLog.objects.get(action="makerspace.updated", makerspace=lab)
    assert entry.actor_id == manager.pk
    assert entry.meta == {"fields": ["country", "default_currency", "opening_hours", "timezone"]}
    assert MakerspacePaymentSettings.objects.filter(makerspace=lab).count() == 1
    existing_charge.refresh_from_db()
    assert existing_charge.currency == "eur"


def test_currency_default_creates_one_settings_row_and_is_shared_with_payment_route(profile):
    lab, _, client = profile
    assert client.patch(route(lab), {"default_currency": "eur"}, format="json").status_code == 200
    payment_route = f"/api/v1/admin/makerspace/{lab.pk}/payment-settings"
    assert client.get(payment_route).data["default_currency"] == "eur"
    assert client.patch(payment_route, {"default_currency": "inr"}, format="json").status_code == 200
    assert client.get(route(lab)).data["default_currency"] == "inr"


@pytest.mark.parametrize("payload,field", [
    ({"timezone": "bad/zone"}, "timezone"), ({"country": "ZZ"}, "country"),
    ({"default_currency": "1$!"}, "default_currency"),
    ({"opening_hours": {"weekly": {"mon": []}, "exceptions": {}}}, "opening_hours"),
    ({"opening_hours": {"weekly": {}, "exceptions": {"2026-02-30": []}}}, "opening_hours"),
    ({"country": None}, "country"), ({"opening_hours": None}, "opening_hours"),
    ({"unknown": 1}, "unknown"),
])
def test_validation_is_typed_400_and_atomic(profile, payload, field):
    lab, _, client = profile
    before = (lab.timezone, lab.country, copy.deepcopy(lab.opening_hours))
    response = client.patch(route(lab), {"timezone": "Asia/Kolkata", **payload}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_profile"
    assert field in response.data["fields"]
    lab.refresh_from_db()
    assert (lab.timezone, lab.country, lab.opening_hours) == before
    assert not AuditLog.objects.filter(action="makerspace.updated", makerspace=lab).exists()


@pytest.mark.parametrize("method", ["get", "patch"])
def test_cross_tenant_manager_cannot_read_or_write_profile(profile, method):
    lab, _, _ = profile
    other = make_space("profile-other")
    other_manager = make_member("profile-other-manager", other)
    client = authenticated_client(other_manager)
    response = client.get(route(lab)) if method == "get" else client.patch(route(lab), {"country": "US"}, format="json")
    assert response.status_code == 404


def test_verified_tenant_origin_can_use_own_profile_but_cannot_cross_tenants(profile):
    lab, manager, client = profile
    lab.frontend_domain = "profile.example.test"
    lab.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    lab.save(update_fields=["frontend_domain", "frontend_domain_status"])
    other = make_space("profile-origin-other")
    MakerspaceMembership.objects.create(user=manager, makerspace=other,
                                       role=MakerspaceMembership.Role.SPACE_MANAGER)
    origin = {"HTTP_ORIGIN": "https://profile.example.test"}
    assert client.get(route(lab), **origin).status_code == 200
    assert client.patch(route(lab), {"country": "IN"}, format="json", **origin).status_code == 200
    assert client.get(route(other), **origin).status_code == 403
    assert client.patch(route(other), {"country": "US"}, format="json", **origin).status_code == 403


def test_inventory_manager_has_no_profile_action(profile):
    lab, _, _ = profile
    actor = make_member("profile-inventory", lab,
                        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
                        role=User.Role.REQUESTER)
    client = authenticated_client(actor)
    assert client.get(route(lab)).status_code == 404
    assert client.patch(route(lab), {"country": "US"}, format="json").status_code == 404


def test_archived_and_hidden_makerspaces_are_not_profile_targets(profile):
    lab, _, client = profile
    lab.archived_at = timezone.now()
    lab.save(update_fields=["archived_at"])
    assert client.get(route(lab)).status_code == 404
    lab.archived_at = None
    lab.superadmin_access_enabled = False
    lab.save(update_fields=["archived_at", "superadmin_access_enabled"])
    superadmin = User.objects.create_user(username="profile-superadmin", role=User.Role.SUPERADMIN)
    assert authenticated_client(superadmin).get(route(lab)).status_code == 404


def test_audit_failure_rolls_back_profile_and_currency(profile, monkeypatch):
    lab, _, client = profile
    original_zone = lab.timezone
    def fail(*args, **kwargs):
        raise RuntimeError("audit failed")
    monkeypatch.setattr("apps.admin_api.views_makerspace_profile.audit.record", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        client.patch(route(lab), {"timezone": "Asia/Kolkata", "default_currency": "eur"}, format="json")
    lab.refresh_from_db()
    assert lab.timezone == original_zone
    assert not MakerspacePaymentSettings.objects.filter(makerspace=lab).exists()


def test_public_bootstrap_exposes_zone_and_hours_but_not_country(profile):
    lab, _, client = profile
    client.patch(route(lab), {"timezone": "Asia/Kolkata", "country": "IN"}, format="json")
    response = client.get(f"/api/v1/bootstrap?slug={lab.slug}")
    assert response.status_code == 200
    public = response.data["makerspace"]
    assert public["timezone"] == "Asia/Kolkata"
    assert public["opening_hours"] == {}
    assert "country" not in public
    assert "default_currency" not in public


def test_profile_fields_and_currency_travel_in_portable_projection(profile):
    from apps.backup.raw_projection import raw_records
    from apps.tenant_migration.tenant_dump_raw import sanitize_record
    from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES, validate_catalog
    from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
    lab, _, client = profile
    hours = {"weekly": {}, "exceptions": {"2026-12-25": []}}
    client.patch(route(lab), {"timezone": "Asia/Kolkata", "country": "IN", "opening_hours": hours, "default_currency": "inr"}, format="json")
    validate_catalog()
    row = raw_records(Makerspace.objects.filter(pk=lab.pk), Makerspace)[0]
    values = sanitize_record(Makerspace, row).values
    for field, expected in {"timezone": "Asia/Kolkata", "country": "IN", "opening_hours": hours}.items():
        assert values[field] == expected
        assert FIELD_POLICIES[("makerspaces.Makerspace", field)].dispositions == (AuthorityDisposition.PRESERVE,)
    row = raw_records(MakerspacePaymentSettings.objects.filter(makerspace=lab), MakerspacePaymentSettings)[0]
    assert sanitize_record(MakerspacePaymentSettings, row).values["default_currency"] == "inr"




def test_noop_patch_does_not_create_settings_or_audit_rows(profile):
    lab, _, client = profile
    original_updated_at = lab.updated_at
    response = client.patch(route(lab), {"default_currency": "usd", "timezone": lab.timezone}, format="json")
    assert response.status_code == 200
    lab.refresh_from_db()
    assert lab.updated_at == original_updated_at
    assert not MakerspacePaymentSettings.objects.filter(makerspace=lab).exists()
    assert not AuditLog.objects.filter(makerspace=lab, action="makerspace.updated").exists()


def test_malformed_json_is_a_typed_profile_error_without_writes(profile):
    lab, _, client = profile
    response = client.patch(route(lab), data='{"country":', content_type="application/json")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_profile"
    assert response.data["fields"]["non_field_errors"]
    assert not AuditLog.objects.filter(makerspace=lab, action="makerspace.updated").exists()


@pytest.mark.parametrize("status", [User.AccessStatus.RESTRICTED, User.AccessStatus.SUSPENDED])
def test_inactive_access_status_blocks_profile_reads_and_writes(profile, status):
    lab, manager, client = profile
    manager.access_status = status
    manager.save(update_fields=["access_status"])
    assert client.get(route(lab)).status_code == 403
    assert client.patch(route(lab), {"country": "IN"}, format="json").status_code == 403
    lab.refresh_from_db()
    assert lab.country == ""


def test_quiesced_source_gate_blocks_profile_patch_but_keeps_reads(profile):
    from tests.tenant_migration.source_gate_helpers import close_gate
    lab, manager, client = profile
    close_gate(lab, manager)
    response = client.patch(route(lab), {"country": "IN", "default_currency": "eur"}, format="json")
    assert response.status_code == 423
    assert response.json()["code"] == "tenant_migration_quiesced"
    assert client.get(route(lab)).status_code == 200
    lab.refresh_from_db()
    assert lab.country == ""
    assert not MakerspacePaymentSettings.objects.filter(makerspace=lab).exists()
    assert not AuditLog.objects.filter(makerspace=lab, action="makerspace.updated").exists()


def test_profile_patch_is_core_with_all_optional_modules_off(profile):
    lab, _, client = profile
    lab.enabled_modules = []
    lab.save(update_fields=["enabled_modules"])
    response = client.patch(route(lab), {
        "timezone": "Asia/Kolkata", "country": "IN", "default_currency": "eur",
        "opening_hours": {"weekly": {}, "exceptions": {"2026-12-25": []}},
    }, format="json")
    assert response.status_code == 200
    assert response.data["default_currency"] == "eur"
    assert AuditLog.objects.filter(makerspace=lab, action="makerspace.updated").count() == 1


def test_payment_validation_failure_rolls_back_created_row_and_profile(profile, monkeypatch):
    from django.core.exceptions import ValidationError
    lab, _, client = profile
    save = MakerspacePaymentSettings.save

    def fail_currency_update(payment, *args, **kwargs):
        if payment.pk:
            raise ValidationError({"default_currency": ["Currency change refused."]})
        return save(payment, *args, **kwargs)

    monkeypatch.setattr(MakerspacePaymentSettings, "save", fail_currency_update)
    response = client.patch(route(lab), {"country": "IN", "default_currency": "eur"}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_profile"
    lab.refresh_from_db()
    assert lab.country == ""
    assert not MakerspacePaymentSettings.objects.filter(makerspace=lab).exists()
    assert not AuditLog.objects.filter(makerspace=lab, action="makerspace.updated").exists()
