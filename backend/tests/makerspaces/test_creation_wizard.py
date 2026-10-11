"""Creation setup is all-or-nothing; invitation delivery is after commit."""
import pytest
from unittest.mock import patch

from apps.audit.models import AuditLog
from apps.accounts.models_staff_invitations import StaffInvitation
from apps.makerspaces.models import Makerspace, SpacePackProfile
from apps.makerspaces.module_registry import core_module_keys
from apps.makerspaces.space_pack_export import export_pack
from apps.payments.models import MakerspacePaymentSettings
from tests.makerspaces.space_pack_helpers import client, person, space

pytestmark = pytest.mark.django_db(transaction=True)
BASE = "/api/v1/admin/makerspaces"


def payload(**changes):
    return {"name": "Forge", "slug": "wizard-forge", "public_code": "FRGE", "location": "Lab", **changes}


def test_creation_profile_modules_and_first_staff_are_audited_and_delivery_follows_commit():
    root = person("wizard-root", superadmin=True)
    setup = {"profile": {"timezone": "Asia/Kolkata", "country": "IN", "opening_hours": {}, "default_currency": "inr"},
             "modules": ["events"], "first_staff_invite": {"email": "desk@example.test", "role_slug": "space_manager"}}
    def delivered(row, raw):
        from django.db import connection
        assert not connection.in_atomic_block
        assert row.email == "desk@example.test"
        assert raw and raw not in str(list(AuditLog.objects.values_list("meta", flat=True)))
        return {"delivery_status": "unavailable", "accept_url": "https://example.test/accept#private"}
    with patch("apps.makerspaces.creation_setup.deliver", side_effect=delivered) as deliver:
        response = client(root).post(BASE, payload(creation_setup=setup), format="json")
    assert response.status_code == 201, response.data
    assert response["Cache-Control"] == "no-store"
    row = Makerspace.objects.get(slug="wizard-forge")
    assert row.timezone == "Asia/Kolkata" and row.country == "IN"
    assert "events" in row.enabled_modules and core_module_keys() <= set(row.enabled_modules)
    assert MakerspacePaymentSettings.objects.get(makerspace=row).default_currency == "inr"
    assert StaffInvitation.objects.get(makerspace=row).created_by == root
    assert response.data["creation_invitation"]["delivery_status"] == "unavailable"
    assert AuditLog.objects.filter(actor=root, makerspace=row, action="makerspace.created").exists()
    assert AuditLog.objects.filter(actor=root, makerspace=row, action="staff.invitation_created").exists()
    deliver.assert_called_once()


@pytest.mark.parametrize("setup", [
    {"profile": {"timezone": "not/a-zone"}}, {"modules": ["unknown"]},
    {"first_staff_invite": {"email": "invalid", "role_slug": "space_manager"}},
    {"profile": {"timezone": "UTC", "enabled_modules": ["events"]}},
    {"profile": {"opening_hours": {"weekly": {"mon": [{"start": "17:00", "end": "09:00"}]}, "exceptions": {}}}},
])
def test_invalid_setup_never_creates_a_makerspace_or_invitation(setup):
    with patch("apps.makerspaces.creation_setup.deliver") as deliver:
        response = client(person("wizard-invalid", superadmin=True)).post(BASE, payload(creation_setup=setup), format="json")
    assert response.status_code == 400, response.data
    assert not Makerspace.objects.filter(slug="wizard-forge").exists()
    assert not StaffInvitation.objects.exists()
    deliver.assert_not_called()


def test_pack_and_explicit_setup_share_one_transaction():
    source, manager = space("wizard-source")
    pack = export_pack(manager, source)
    profile = SpacePackProfile.objects.create(name="Wizard pack", pack=pack)
    root = person("wizard-create-root", superadmin=True)
    response = client(root).post(BASE, payload(install_profile_id=profile.pk, creation_setup={"profile": {"timezone": "Europe/London"}}), format="json")
    assert response.status_code == 201, response.data
    assert Makerspace.objects.get(slug="wizard-forge").timezone == "Europe/London"


def test_creation_setup_cannot_be_replayed_on_settings_patch():
    row, actor = space("wizard-patch")
    before = list(row.enabled_modules)
    response = client(actor).patch(f"{BASE}/{row.pk}", {"creation_setup": {"modules": ["events"]}}, format="json")
    assert response.status_code == 400, response.data
    row.refresh_from_db()
    assert row.enabled_modules == before
    assert not AuditLog.objects.filter(makerspace=row, action="makerspace.updated").exists()


def test_nested_profile_validates_without_standalone_initial_data():
    from apps.admin_api.serializers_creation_setup import MakerspaceCreationSetupSerializer
    serializer = MakerspaceCreationSetupSerializer(data={"profile": {"timezone": "UTC"}})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"profile": {"timezone": "UTC"}}


def test_invitation_feature_off_rolls_back_creation_and_never_delivers():
    source, manager = space("wizard-invites-off")
    source.enabled_features = [key for key in source.enabled_features if key != "staff.invitations"]
    source.save(update_fields=["enabled_features"])
    pack = export_pack(manager, source)
    profile = SpacePackProfile.objects.create(name="Invites off", pack=pack)
    with patch("apps.makerspaces.creation_setup.deliver") as delivery:
        response = client(person("wizard-off-root", superadmin=True)).post(
            BASE, payload(install_profile_id=profile.pk, creation_setup={
                "first_staff_invite": {"email": "desk@example.test", "role_slug": "space_manager"}
            }), format="json",
        )
    assert response.status_code == 400, response.data
    assert not Makerspace.objects.filter(slug="wizard-forge").exists()
    assert not StaffInvitation.objects.exists()
    delivery.assert_not_called()
