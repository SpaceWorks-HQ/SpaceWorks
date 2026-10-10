import pytest

from apps.makerspaces import member_card_services
from apps.makerspaces.models import Makerspace
from tests.rbac_f6_helpers import community_member, custom_actor
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("operation", ["reissue", "revoke", "print", "sheet", "resolve", "template-read", "template-write"])
@pytest.mark.parametrize("authority", ["narrow", "missing", "foreign", "hidden-superadmin"])
def test_manage_members_implies_every_card_operation(operation, authority, monkeypatch):
    space = make_space("f6-card-matrix")
    member = community_member(space)
    manager = make_member("f6-card-manager", space)
    card = member_card_services.issue_card(manager, member)
    qr = member_card_services.active_qr(card)
    if authority == "hidden-superadmin":
        Makerspace.objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
        actor = make_user("f6-card-hidden", role="superadmin", access_status="active")
    else:
        actor = custom_actor(make_space("f6-card-other") if authority == "foreign" else space,
                             [] if authority == "missing" else ["manage_members"])
    monkeypatch.setattr("apps.makerspaces.member_card_printing.render_cards_pdf", lambda *a, **kw: b"%PDF-test")
    base = "/api/v1/admin"
    template_url = f"{base}/makerspaces/{space.pk}/member-card-template"
    routes = {
        "reissue": ("post", f"{base}/member-cards/{card.pk}/reissue", {"reason": "lost"}),
        "revoke": ("post", f"{base}/member-cards/{card.pk}/revoke", {"reason": "revoked"}),
        "print": ("post", f"{base}/member-cards/{card.pk}/print.pdf", {}),
        "sheet": ("post", f"{base}/makerspaces/{space.pk}/member-cards.pdf", {"card_ids": [card.pk]}),
        "resolve": ("post", f"{base}/makerspaces/{space.pk}/member-cards/resolve", {"payload": qr.payload}),
        "template-read": ("get", template_url, None),
        "template-write": ("put", template_url, {}),
    }
    if operation == "template-write":
        from apps.makerspaces.member_card_templates import template_for
        routes[operation] = ("put", template_url, template_for(space))
    method, path, body = routes[operation]
    response = getattr(authenticated_client(actor), method)(path, body, format="json")
    assert response.status_code == (200 if authority == "narrow" else 404)


@pytest.mark.parametrize("authority", ["narrow", "missing", "foreign", "inventory"])
def test_member_verification_route_accepts_manage_members(authority):
    space = make_space("f6-verification")
    member = community_member(space)
    if authority == "inventory":
        actor = make_member("f6-verify-inventory", space, membership_role="inventory_manager", role="requester")
    else:
        actor = custom_actor(make_space("f6-verify-other") if authority == "foreign" else space,
                             [] if authority == "missing" else ["manage_members"])
    response = authenticated_client(actor).post(
        f"/api/v1/member/makerspaces/{space.pk}/verification",
        {"membership_id": member.pk, "verified": True}, format="json",
    )
    assert response.status_code == (200 if authority == "narrow" else 404)
