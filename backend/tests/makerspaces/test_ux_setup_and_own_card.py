"""Wave 5 UX projections: real progress, own QR privacy, no mutation on reads."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models_staff_invitations import StaffInvitation
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.makerspaces import member_card_services as cards
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def setup_url(space):
    return reverse("admin-makerspace-setup-state", args=[space.pk])


def test_setup_reads_real_state_without_modules_or_writing_rows():
    space = make_space("ux-setup-empty")
    manager = make_member("ux-setup-manager", space)
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])
    before = AuditLog.objects.count()
    response = authenticated_client(manager).get(setup_url(space))
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.data == dict(profile_set=False, hours_set=False, first_item_added=False,
                                 staff_invited=False, modules_chosen=False)
    assert AuditLog.objects.count() == before


def test_setup_progress_is_tenant_scoped_and_derived():
    space, other = make_space("ux-setup-full"), make_space("ux-setup-other")
    manager = make_member("ux-setup-full-manager", space)
    client = authenticated_client(manager)
    assert client.get(setup_url(other)).status_code == 404
    make_product(other)
    assert client.get(setup_url(space)).data["first_item_added"] is False
    space.location = "Workshop 1"
    space.opening_hours = {"weekly": {day: [] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}, "exceptions": {}}
    space.save(update_fields=["location", "opening_hours"])
    make_product(space)
    role = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
    StaffInvitation.objects.create(makerspace=space, role=role, created_by=manager,
                                   email_ciphertext="", token_digest="a" * 64,
                                   expires_at=timezone.now() + timedelta(days=1))
    audit.record(manager, "makerspace.capabilities_changed", makerspace=space, target=space,
                 meta={"before": {"modules": []}, "after": {"modules": ["machines"]}})
    response = client.get(setup_url(space))
    assert response.status_code == 200
    assert all(response.data.values())


def test_inventory_manager_cannot_read_setup_state():
    space = make_space("ux-setup-denied")
    actor = make_member("ux-inventory-only", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    assert authenticated_client(actor).get(setup_url(space)).status_code == 404


def test_feature_only_change_does_not_claim_modules_were_chosen():
    space = make_space("ux-setup-feature-only")
    manager = make_member("ux-setup-feature-manager", space)
    audit.record(manager, "makerspace.capabilities_changed", makerspace=space, target=space,
                 meta={"before": {"modules": ["staff_admin"], "features": []},
                       "after": {"modules": ["staff_admin"], "features": ["staff.invitations"]}})
    assert authenticated_client(manager).get(setup_url(space)).data["modules_chosen"] is False


def test_own_card_contains_only_own_qr_and_never_a_photo_key():
    space = make_space("ux-own-card")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"membership"})
    space.save(update_fields=["enabled_modules"])
    manager = make_member("ux-card-manager", space)
    owner = make_member("ux-card-owner", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    membership = MakerspaceMembership.objects.get(user=owner, makerspace=space)
    card = cards.issue_card(manager, membership, printed_name="Owner")
    url = reverse("member-card", args=[space.pk])
    response = authenticated_client(owner).get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.data["qr_image"].startswith("data:image/png;base64,")
    assert response.data["qr_active"] is True
    assert "photo_object_key" not in response.data and "qr_payload" not in response.data
    stranger = make_member("ux-card-stranger", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    assert authenticated_client(stranger).get(url).status_code == 404
    first_image = response.data["qr_image"]
    cards.reissue_card(manager, card, reason="lost")
    assert authenticated_client(owner).get(url).data["qr_image"] != first_image
    cards.revoke_card(manager, card)
    assert authenticated_client(owner).get(url).status_code == 404


def test_own_card_refuses_module_off():
    space = make_space("ux-card-off")
    actor = make_member("ux-card-off-member", space)
    space.enabled_modules = [key for key in space.enabled_modules if key != "membership"]
    space.save(update_fields=["enabled_modules"])
    assert authenticated_client(actor).get(reverse("member-card", args=[space.pk])).status_code == 400


def test_own_card_never_exposes_a_revoked_qr_or_a_foreign_card():
    from apps.boxes.models import QrCode
    from apps.boxes.services import revoke_qr_code

    space, other = make_space("ux-qr-only-revoked"), make_space("ux-card-foreign")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"membership"})
    space.save(update_fields=["enabled_modules"])
    manager = make_member("ux-qr-manager", space)
    membership = MakerspaceMembership.objects.get(user=manager, makerspace=space)
    card = cards.issue_card(manager, membership, printed_name="Manager")
    before = AuditLog.objects.count()
    client = authenticated_client(manager)
    assert client.get(reverse("member-card", args=[other.pk])).status_code == 403
    assert client.get(reverse("member-card", args=[space.pk])).status_code == 200
    assert AuditLog.objects.count() == before
    qr = QrCode.objects.get(target_id=card.pk, target_type=QrCode.TargetType.MEMBER_CARD)
    revoke_qr_code(manager, qr)
    response = client.get(reverse("member-card", args=[space.pk]))
    assert response.status_code == 200
    assert response.data["qr_active"] is False
    assert response.data["qr_image"] is None
