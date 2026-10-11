import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.events import services
from apps.makerspaces.models import MakerspaceMembership
from tests.events.collab_helpers import make_member, make_staff, client_for, collaborate
from tests.events.ticketing_helpers import event_space, account, open_event, signup, public_url

pytestmark = pytest.mark.django_db


def test_accounts_audience_works_with_no_membership_or_payment_module():
    space = event_space()
    attendee = account()
    event = open_event(space)
    assert signup(event, attendee).status_code == 201
    assert event.registrations.get().member == attendee
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=attendee).exists()


def test_members_default_still_requires_membership_and_anonymous_is_refused():
    space = event_space(membership=True)
    event = open_event(space, "members")
    assert signup(event, account()).status_code == 403
    assert APIClient().post(public_url(event), {}, format="json").status_code == 401
    assert signup(event, make_member(space)).status_code == 201


@pytest.mark.parametrize("field,value", [("is_active", False), ("access_status", "restricted"), ("access_status", "suspended")])
def test_accounts_registration_cannot_bypass_account_standing(field, value):
    space = event_space()
    user = account()
    setattr(user, field, value)
    user.save(update_fields=[field])
    assert signup(open_event(space), user).status_code == 403


def test_staff_can_register_an_account_without_inventing_a_membership():
    space = event_space()
    staff, user = make_staff(space), account()
    event = open_event(space)
    event.is_public = False
    event.save(update_fields=["is_public"])
    response = client_for(staff).post(reverse("admin-event-registration-list", args=[event.pk]), {"member_id": user.pk}, format="json")
    assert response.status_code == 201, response.data
    assert event.registrations.get().member == user
    assert not MakerspaceMembership.objects.filter(user=user).exists()


def test_collaborative_service_still_requires_a_member_of_the_collaborating_space():
    host, partner = event_space("host"), event_space("partner", membership=True)
    event = open_event(host)
    collaborate(event, partner)
    from apps.presence.guard import MemberPresenceRequired
    with pytest.raises(MemberPresenceRequired):
        services.register(event, member=account(), collaborative=True, via_makerspace=partner)


def test_audience_feature_off_refuses_and_module_off_is_400():
    space = event_space()
    event = open_event(space)
    user = account()
    space.enabled_features = [key for key in space.enabled_features if key != "events.account_registration"]
    space.save(update_fields=["enabled_features"])
    assert signup(event, user).status_code == 400
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])
    assert signup(event, user).status_code == 400


@pytest.mark.parametrize("missing,value", [("phone", "1234567890"), ("email", "fallback@example.test")])
def test_account_signup_with_missing_contact_can_supply_a_fallback(missing, value):
    space = event_space()
    event = open_event(space)
    user = account()
    setattr(user, missing, "")
    user.save(update_fields=[missing])
    refused = signup(event, user)
    assert refused.status_code == 400 and missing in refused.data
    assert signup(event, user, **{missing: value}).status_code == 201
    assert getattr(event.registrations.get(), missing) == value


def test_contact_fallback_cannot_replace_account_identity_or_bind_an_invite():
    from apps.events.invites import create_invite
    space = event_space()
    event = open_event(space)
    user = account()
    assert signup(event, user, email="someone-else@example.test", phone="another-number").status_code == 201
    registration = event.registrations.get()
    assert registration.email == user.email and registration.phone == user.phone
    invited = open_event(space, "invite")
    _, code = create_invite(invited, actor=make_staff(space), email="someone-else@example.test")
    assert signup(invited, user, email="someone-else@example.test", invite_code=code).status_code == 404
