"""Member-card paths the audit found built but untested (00-audit.md §3).

Photo consent and storage accounting, reprint vs revoked print, the `inactive` scan outcome,
a box QR at the card resolver, issuing to a non-active membership, and custom roles holding
no card action by default.
"""
import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.boxes.models import Box, QrCode
from apps.makerspaces import member_card_services as services
from apps.makerspaces import member_card_storage
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)


def _membership(makerspace, name, **fields):
    return MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user(name), assigned_role=member_role(makerspace), role="custom",
        **fields,
    )


@pytest.fixture
def fake_bucket(monkeypatch):
    deleted = []
    monkeypatch.setattr("apps.evidence.storage.object_size", lambda key: 1500)
    monkeypatch.setattr("apps.evidence.storage.validate_evidence_object", lambda key: None)
    monkeypatch.setattr("apps.evidence.storage.copy_object", lambda source, target: None)
    monkeypatch.setattr("apps.evidence.storage.delete_object", lambda key: deleted.append(key))
    return deleted


def _storage(makerspace):
    return Makerspace.objects.get(pk=makerspace.pk).storage_bytes_used


def test_a_photo_needs_consent_and_is_charged_then_freed_on_revoke(fake_bucket, settings):
    # Storage is metered only on a managed box; self-host is unlimited and never counts.
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    makerspace = space("card-photo")
    boss = manager(makerspace, "card-photo-manager")
    membership = _membership(makerspace, "card-photo-member")
    card = services.issue_card(boss, membership, printed_name="Ada")
    key = f"member-cards/{makerspace.pk}/{'a' * 32}"
    before = _storage(makerspace)

    with pytest.raises(ValidationError) as refused:
        member_card_storage.finalize_photo(
            membership.user, card, object_key=key, content_type="image/png", consent=False,
        )
    assert "consent" in refused.value.detail
    assert _storage(makerspace) == before

    card = member_card_storage.finalize_photo(
        membership.user, card, object_key=key, content_type="image/png", consent=True,
    )
    assert card.photo_object_key == key and card.photo_consent_at is not None
    assert _storage(makerspace) == before + 1500

    services.revoke_card(boss, card, reason="left")

    assert key in fake_bucket
    assert _storage(makerspace) == before


def test_a_photo_key_from_another_makerspace_is_refused(fake_bucket):
    makerspace, other = space("card-photo-tenant"), space("card-photo-tenant-other")
    boss = manager(makerspace, "card-photo-tenant-manager")
    membership = _membership(makerspace, "card-photo-tenant-member")
    card = services.issue_card(boss, membership)

    with pytest.raises(ValidationError):
        member_card_storage.finalize_photo(
            membership.user, card, object_key=f"member-cards/{other.pk}/{'b' * 32}",
            content_type="image/png", consent=True,
        )


def test_reprint_keeps_the_qr_and_a_revoked_card_cannot_print():
    makerspace = space("card-reprint")
    boss = manager(makerspace, "card-reprint-manager")
    card = services.issue_card(boss, _membership(makerspace, "card-reprint-member"))
    qr = services.active_qr(card)
    client = authenticated_client(boss)
    url = reverse("admin-member-card-print", kwargs={"pk": card.pk})

    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 200
    assert services.active_qr(card).pk == qr.pk
    card.refresh_from_db()
    assert card.print_count == 2

    services.revoke_card(boss, card)
    assert client.post(url).status_code != 200


def test_a_live_card_of_a_revoked_membership_scans_as_inactive():
    # The state rows revoked before membership revocation took the card with it are in.
    makerspace = space("card-inactive")
    boss = manager(makerspace, "card-inactive-manager")
    membership = _membership(makerspace, "card-inactive-member")
    card = services.issue_card(boss, membership)
    MakerspaceMembership.objects.filter(pk=membership.pk).update(status="revoked")

    assert services.resolve(boss, makerspace, services.active_qr(card).payload) == {"outcome": "inactive"}


def test_a_box_qr_at_the_card_resolver_is_the_same_404_as_garbage():
    makerspace = space("card-box-qr")
    boss = manager(makerspace, "card-box-qr-manager")
    box = Box.objects.create(makerspace=makerspace, label="Shelf")
    box_qr = QrCode.objects.create(makerspace=makerspace, target_type=QrCode.TargetType.BOX, target_id=box.pk)

    for payload in (box_qr.payload, "garbage"):
        with pytest.raises(Http404):
            services.resolve(boss, makerspace, payload)


def test_a_card_is_never_issued_to_a_non_active_membership():
    makerspace = space("card-non-active")
    boss = manager(makerspace, "card-non-active-manager")

    with pytest.raises(PermissionDenied):
        services.issue_card(boss, _membership(makerspace, "card-non-active-member", status="revoked"))


def test_a_custom_role_holds_no_card_action_until_granted():
    makerspace = space("card-custom-role")
    clerk = user("card-custom-role-clerk")
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=clerk, role="custom",
        assigned_role=MakerspaceRole.objects.create(
            makerspace=makerspace, slug="clerk", name="Clerk", granted_actions=["view_inventory"],
        ),
    )

    assert not rbac.can(clerk, rbac.Action.MANAGE_MEMBER_CARDS, makerspace.pk)
    assert not rbac.can(clerk, rbac.Action.SCAN_MEMBER_CARDS, makerspace.pk)
