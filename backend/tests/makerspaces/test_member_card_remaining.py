"""Remaining card audit rows: print presets, inactive resolution, action defaults."""
import re

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.makerspaces import member_card_services as cards
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def _pdf_pages_and_first_mediabox(content):
    """Page count and first MediaBox from reportlab's uncompressed page dictionaries.

    reportlab is the only PDF library the project ships; it writes `/Type /Page` and
    `/MediaBox [x0 y0 x1 y1]` as plain text, so a reader dependency is not needed here.
    """
    text = content.decode("latin-1")
    pages = len(re.findall(r"/Type\s*/Page\b(?!s)", text))
    match = re.search(r"/MediaBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]", text)
    assert match, "no MediaBox in generated PDF"
    return pages, tuple(float(value) for value in match.groups())


def card_state():
    makerspace = space("remaining-card")
    boss = manager(makerspace, "remaining-card-manager")
    row = MakerspaceMembership.objects.create(makerspace=makerspace, user=user("remaining-card-member"), assigned_role=member_role(makerspace), role="custom")
    card = cards.issue_card(boss, row, printed_name="Member Name")
    return makerspace, boss, row, card


@pytest.mark.parametrize("preset,page,expected", [("sheet", "letter", (612, 792)), ("single", "letter", (85.6 * 72 / 25.4, 54 * 72 / 25.4))])
def test_print_presets_have_expected_pdf_size_and_do_not_rotate_qr(preset, page, expected):
    makerspace, boss, _, card = card_state()
    client = authenticated_client(boss)
    assert client.put(reverse("admin-member-card-template", args=[makerspace.pk]), {"page": page}, format="json").status_code == 200
    qr = cards.active_qr(card)
    response = client.post(reverse("admin-member-cards-sheet", args=[makerspace.pk]), {"card_ids": [card.pk], "preset": preset}, format="json")
    assert response.status_code == 200
    pages, mediabox = _pdf_pages_and_first_mediabox(response.content)
    assert pages == 1
    assert (mediabox[2] - mediabox[0], mediabox[3] - mediabox[1]) == pytest.approx(expected, abs=0.01)
    assert cards.active_qr(card).pk == qr.pk
    assert AuditLog.objects.filter(action="member_card.printed", actor=boss, makerspace=makerspace).exists()
    assert AuditLog.objects.filter(action="member_card.template_updated", actor=boss, makerspace=makerspace).exists()
    card.refresh_from_db(); assert card.print_count == 1


def test_revoked_card_cannot_print_and_does_not_record_another_print():
    _, boss, _, card = card_state()
    cards.revoke_card(boss, card)
    response = authenticated_client(boss).post(reverse("admin-member-card-print", args=[card.pk]))
    assert response.status_code == 403
    card.refresh_from_db(); assert card.print_count == 0
    assert not AuditLog.objects.filter(action="member_card.printed").exists()


def test_inactive_membership_scan_records_inactive_without_identity_payload():
    makerspace, boss, row, card = card_state()
    payload = cards.active_qr(card).payload
    MakerspaceMembership.objects.filter(pk=row.pk).update(status="revoked")
    assert cards.resolve(boss, makerspace, payload) == {"outcome": "inactive"}
    assert QrScanEvent.objects.filter(context="member_lookup", qr_code__target_id=card.pk).count() == 1
    assert AuditLog.objects.get(action="member_card.scanned").meta["outcome"] == "inactive"


def test_box_qr_cannot_resolve_as_a_member_and_custom_roles_gain_no_card_actions():
    makerspace, boss, _, _ = card_state()
    box = Box.objects.create(makerspace=makerspace, label="Box")
    qr = QrCode.objects.create(makerspace=makerspace, target_type=QrCode.TargetType.BOX, target_id=box.pk)
    with pytest.raises(Http404):
        cards.resolve(boss, makerspace, qr.payload)
    custom = MakerspaceRole.objects.create(makerspace=makerspace, name="Custom", slug="custom", granted_actions=[rbac.Action.VIEW_INVENTORY])
    person = user("card-custom-role")
    MakerspaceMembership.objects.create(makerspace=makerspace, user=person, assigned_role=custom, role="custom")
    assert not rbac.can(person, rbac.Action.MANAGE_MEMBER_CARDS, makerspace.pk)
    assert not rbac.can(person, rbac.Action.SCAN_MEMBER_CARDS, makerspace.pk)


def test_card_issue_refuses_revoked_members_and_name_and_reissue_are_audited():
    makerspace, boss, row, card = card_state()
    client = authenticated_client(row.user)
    assert client.patch(reverse("member-card", args=[makerspace.pk]), {"printed_name": "Updated"}, format="json").status_code == 200
    cards.reissue_card(boss, card, reason="lost")
    assert AuditLog.objects.filter(action="member_card.name_updated", actor=row.user, makerspace=makerspace).exists()
    assert AuditLog.objects.filter(action="member_card.reissued", actor=boss, makerspace=makerspace).exists()
    MakerspaceMembership.objects.filter(pk=row.pk).update(status="revoked")
    with pytest.raises(PermissionDenied, match="Only an active membership"):
        cards.issue_card(boss, row)
