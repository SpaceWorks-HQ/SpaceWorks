"""Member ID cards: issue, reissue, revoke/redact, dedicated resolution, printing, purge."""
import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from apps.makerspaces import member_card_services as services
from apps.makerspaces import member_card_storage, member_card_templates
from apps.makerspaces.models import MakerspaceMembership, MemberCard
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def _member(space, name="card-member"):
    user = make_user(name, access_status="active")
    return MakerspaceMembership.objects.create(user=user, makerspace=space, role=MakerspaceMembership.Role.INVENTORY_MANAGER)


def _inventory_only(space, name):
    """Holds VIEW_INVENTORY through the protected default role but no member-card action."""
    return make_member(name, space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)


def test_space_manager_holds_manage_and_implied_scan():
    space = make_space("cards-rbac")
    manager = make_member("cards-manager", space)
    assert rbac.can(manager, rbac.Action.MANAGE_MEMBER_CARDS, space.pk)
    assert rbac.can(manager, rbac.Action.SCAN_MEMBER_CARDS, space.pk)
    inventory = _inventory_only(space, "cards-inventory")
    assert rbac.can(inventory, rbac.Action.VIEW_INVENTORY, space.pk)
    assert not rbac.can(inventory, rbac.Action.SCAN_MEMBER_CARDS, space.pk)


def test_issue_creates_one_active_qr_and_sequential_numbers():
    space = make_space("cards-issue")
    manager = make_member("cards-issuer", space)
    first = services.issue_card(manager, _member(space, "m1"), printed_name="Ada L.")
    second = services.issue_card(manager, _member(space, "m2"))
    assert (first.card_number, second.card_number) == (1, 2)
    qrs = QrCode.objects.filter(target_type="member_card", target_id=first.pk)
    assert qrs.count() == 1 and qrs.get().status == QrCode.Status.ACTIVE
    assert AuditLog.objects.filter(action="member_card.issued").count() == 2
    with pytest.raises(PermissionDenied):
        services.issue_card(manager, first.membership)  # one card per membership


def test_reissue_rotates_the_qr_and_old_payload_scans_as_revoked():
    space = make_space("cards-reissue")
    manager = make_member("cards-reissuer", space)
    card = services.issue_card(manager, _member(space))
    old = services.active_qr(card)
    services.reissue_card(manager, card, reason="lost")
    new = services.active_qr(card)
    assert new.pk != old.pk
    old.refresh_from_db()
    assert old.status == QrCode.Status.REVOKED
    assert services.resolve(manager, space, old.payload) == {"outcome": "revoked"}
    assert services.resolve(manager, space, new.payload)["card_number"] == card.card_number
    assert QrScanEvent.objects.filter(context="member_lookup").count() == 2
    with pytest.raises(PermissionDenied):
        services.reissue_card(manager, card, reason="because")


def test_resolution_is_action_gated_uniformly_refused_and_never_through_the_scanner():
    alpha, beta = make_space("cards-alpha"), make_space("cards-beta")
    manager = make_member("cards-alpha-manager", alpha)
    card = services.issue_card(manager, _member(alpha))
    payload = services.active_qr(card).payload
    inventory = _inventory_only(alpha, "cards-alpha-inventory")
    with pytest.raises(PermissionDenied):
        services.resolve(inventory, alpha, payload)
    beta_manager = make_member("cards-beta-manager", beta)
    with pytest.raises(Http404):
        services.resolve(beta_manager, beta, payload)  # another tenant's card: looks like nothing
    with pytest.raises(Http404):
        services.resolve(manager, alpha, "not-a-real-payload")
    # The generic inventory scanner refuses to resolve a person.
    response = authenticated_client(manager).post("/api/v1/admin/qr/resolve", {"payload": payload}, format="json")
    assert response.status_code == 404


def test_revoke_redacts_name_and_photo_and_keeps_row_qr_scans_and_audit(monkeypatch):
    space = make_space("cards-revoke")
    manager = make_member("cards-revoker", space)
    card = services.issue_card(manager, _member(space), printed_name="Grace H.")
    card.photo_object_key = f"member-cards/{space.pk}/abc"
    card.photo_content_type = "image/jpeg"
    card.photo_size_bytes = 1200
    card.photo_consent_at = card.issued_at
    card.photo_consent_version = "2026-09"
    card.save()
    deleted = []
    monkeypatch.setattr(member_card_storage.storage, "delete_object", lambda key: deleted.append(key))
    services.resolve(manager, space, services.active_qr(card).payload)
    services.revoke_card(manager, card, reason="left")
    card.refresh_from_db()
    assert card.revoked_at is not None and card.revoked_reason == "left"
    assert card.printed_name == "" and card.photo_object_key == "" and card.photo_size_bytes is None
    assert deleted == [f"member-cards/{space.pk}/abc"]
    assert QrCode.objects.filter(target_type="member_card", target_id=card.pk, status="revoked").count() == 1
    assert QrScanEvent.objects.filter(context="member_lookup").count() == 1
    assert AuditLog.objects.filter(action="member_card.revoked").exists()


def test_staff_api_issue_print_and_sheet(monkeypatch):
    space = make_space("cards-api")
    manager = make_member("cards-api-manager", space)
    membership = _member(space)
    client = authenticated_client(manager)
    issue_url = reverse("admin-member-card-issue", kwargs={"makerspace_id": space.pk, "membership_id": membership.pk})
    created = client.post(issue_url, {"printed_name": "Mary J."}, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["photo_set"] is False and body["is_active"] is True and "photo_object_key" not in body
    card_id = body["id"]
    monkeypatch.setattr(member_card_storage, "photo_bytes", lambda card: None)
    single = client.post(reverse("admin-member-card-print", kwargs={"pk": card_id}))
    assert single.status_code == 200 and single["Content-Type"] == "application/pdf"
    assert single.content.startswith(b"%PDF")
    sheet = client.post(reverse("admin-member-cards-sheet", kwargs={"makerspace_id": space.pk}), {"preset": "sheet"}, format="json")
    assert sheet.status_code == 200 and sheet.content.startswith(b"%PDF")
    card = MemberCard.objects.get(pk=card_id)
    assert card.print_count == 2
    listed = client.get(reverse("admin-member-cards", kwargs={"makerspace_id": space.pk}), {"status": "active"}).json()
    assert listed["count"] == 1
    # An inventory-only role cannot reach any of it.
    other = authenticated_client(_inventory_only(space, "cards-api-inventory"))
    assert other.get(reverse("admin-member-cards", kwargs={"makerspace_id": space.pk})).status_code == 404
    assert other.post(reverse("admin-member-card-print", kwargs={"pk": card_id})).status_code == 404


def test_member_reads_own_card_and_preview_but_not_someone_elses():
    space = make_space("cards-member")
    manager = make_member("cards-member-manager", space)
    membership = _member(space, "owner")
    services.issue_card(manager, membership, printed_name="Owner")
    stranger = _member(space, "stranger")
    own = authenticated_client(membership.user)
    url = reverse("member-card", kwargs={"makerspace_id": space.pk})
    assert own.get(url).json()["printed_name"] == "Owner"
    assert own.patch(url, {"printed_name": "O. Wner"}, format="json").status_code == 200
    preview = own.get(reverse("member-card-preview", kwargs={"makerspace_id": space.pk}))
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF")
    assert authenticated_client(stranger.user).get(url).status_code == 404


def test_template_round_trip_and_validation():
    space = make_space("cards-template")
    manager = make_member("cards-template-manager", space)
    client = authenticated_client(manager)
    url = reverse("admin-member-card-template", kwargs={"makerspace_id": space.pk})
    assert client.get(url).json()["page"] == "a4"
    saved = client.put(url, {"page": "letter", "front_fields": ["printed_name", "card_number"], "font_size_pt": 9}, format="json")
    assert saved.status_code == 200 and saved.json()["page"] == "letter"
    space.refresh_from_db()  # the view saved its own instance; this one is stale
    assert member_card_templates.template_for(space)["front_fields"] == ["printed_name", "card_number"]
    bad = client.put(url, {"page": "poster"}, format="json")
    assert bad.status_code == 400
    width, height, columns, rows = member_card_templates.page_layout(member_card_templates.template_for(space))
    assert columns * rows >= 8  # a Letter sheet holds a full run of CR80 cards


def test_membership_purge_revokes_qrs_and_deletes_cards(monkeypatch):
    from apps.makerspaces.module_purge_plans import PLANS

    space = make_space("cards-purge")
    manager = make_member("cards-purge-manager", space)
    card = services.issue_card(manager, _member(space))
    plan = next(plan for plan in PLANS if plan.key == "membership")
    assert "makerspaces.MemberCard" in plan.pii_labels
    collected = []
    plan.private_keys(space, collected.append)
    assert collected == []
    plan.delete(space, None)
    assert not MemberCard.objects.filter(pk=card.pk).exists()
    assert QrCode.objects.filter(target_type="member_card", target_id=card.pk, status="revoked").exists()
