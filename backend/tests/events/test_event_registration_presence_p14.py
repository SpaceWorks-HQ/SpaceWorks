"""Phase 0: event registration requires membership + waiver, but NOT presence.

Registering for an event is planning to attend, not attending. A member signing up in
advance from home cannot hold an open `PresenceSession`, so requiring one made advance
registration impossible and made a collaborating space's member unable to register at all.
Physical attendance is established instead by the staff-scanned QR check-in, which is
stronger evidence than a self-declared session.

What must NOT change is every other flow that asks the same question. Those are hardware
and facility actions where "is this member physically here right now" is the point, so
`require_active_member_presence` keeps its session requirement and keeps its callers.
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
)
from apps.makerspaces.waiver_services import accept_waiver
from apps.presence import services as presence_services
from apps.presence.guard import (
    MemberPresenceRequired,
    PresenceRequired,
    WaiverAcceptanceRequired,
    require_active_member,
    require_active_member_presence,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def make_space(slug="presence-split"):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_event(space, **values):
    start = values.pop("starts_at", timezone.now() + timedelta(days=1))
    defaults = {
        "starts_at": start,
        "ends_at": values.pop("ends_at", start + timedelta(hours=2)),
        "is_public": True,
        "status": Event.Status.PUBLISHED,
    }
    defaults.update(values)
    return Event.objects.create(makerspace=space, title="Workshop", **defaults)


def make_member(space, username, *, membership=True, accept=True, session=False):
    """A member with each precondition independently controllable.

    Deliberately not `tests.member_submission.active_member_client`: that helper always
    opens a presence session, which is the one thing these tests need absent.
    """
    user = User.objects.create_user(
        username=username,
        password="password",
        display_name=username,
        email=f"{username}@example.test",
        phone="1234567890",
        access_status=User.AccessStatus.ACTIVE,
    )
    if membership:
        member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
        row = MakerspaceMembership.objects.create(
            makerspace=space,
            user=user,
            role=MakerspaceMembership.Role.CUSTOM,
            assigned_role=member_role,
        )
        if accept and MakerspaceWaiver.objects.filter(
            makerspace=space, is_active=True
        ).exists():
            accept_waiver(row)
    if session:
        presence_services.start_session(user, space, 60)
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def register_url(space, event):
    return reverse(
        "public-event-register",
        kwargs={"makerspace_slug": space.slug, "public_token": event.public_token},
    )


# --- the behaviour change -----------------------------------------------------------


def test_member_without_a_presence_session_can_register():
    space = make_space()
    event = make_event(space)
    _, client = make_member(space, "advance-signup", session=False)

    response = client.post(register_url(space, event), {}, format="json")

    assert response.status_code == 201
    assert response.data == {"status": EventRegistration.Status.REGISTERED}
    assert EventRegistration.objects.filter(event=event).count() == 1


def test_registration_still_works_with_a_presence_session():
    """The relaxation must not invert into a refusal for members who ARE checked in."""
    space = make_space()
    event = make_event(space)
    _, client = make_member(space, "onsite-signup", session=True)

    assert client.post(register_url(space, event), {}, format="json").status_code == 201


# --- what must still be refused ----------------------------------------------------


def test_registration_still_requires_a_membership():
    space = make_space()
    event = make_event(space)
    _, client = make_member(space, "no-membership", membership=False)

    assert client.post(register_url(space, event), {}, format="json").status_code == 403
    assert not EventRegistration.objects.filter(event=event).exists()


def test_registration_still_requires_the_current_waiver():
    space = make_space()
    MakerspaceWaiver.objects.create(
        makerspace=space, is_active=True, version=1, body="Be careful."
    )
    event = make_event(space)
    _, client = make_member(space, "no-waiver", accept=False)

    assert client.post(register_url(space, event), {}, format="json").status_code == 403
    assert not EventRegistration.objects.filter(event=event).exists()


# --- the guard split itself --------------------------------------------------------


def test_require_active_member_does_not_require_a_session():
    space = make_space()
    user, _ = make_member(space, "guard-no-session", session=False)

    result = require_active_member(user, space)

    assert result.membership.user_id == user.pk
    # None is the honest answer: this half never looked for a session.
    assert result.session is None


def test_require_active_member_presence_still_requires_a_session():
    """The other nine invocations all route through this one function."""
    space = make_space()
    user, _ = make_member(space, "guard-presence", session=False)

    with pytest.raises(PresenceRequired):
        require_active_member_presence(user, space)


def test_require_active_member_presence_returns_the_session_when_open():
    space = make_space()
    user, _ = make_member(space, "guard-with-session", session=True)

    result = require_active_member_presence(user, space)

    assert result.session is not None
    assert result.session.member_id == user.pk


def test_require_active_member_presence_skips_the_session_when_presence_tombstoned(
    monkeypatch,
):
    """The one branch where removing an app changes behaviour rather than a surface.

    A deployment that does not ship check-in has no session for any caller to find, so a
    hard requirement would make every one of those flows refuse forever. This branch moved
    during the guard split, so it is asserted directly: the tombstone suite cannot reach it
    here because that profile tombstones `events` as well.
    """
    space = make_space()
    user, _ = make_member(space, "presence-tombstoned", session=False)
    monkeypatch.setattr(
        "apps.presence.guard.runtime_active", lambda label: label != "presence"
    )

    result = require_active_member_presence(user, space)

    assert result.session is None
    assert result.membership.user_id == user.pk


@pytest.mark.parametrize("guard", [require_active_member, require_active_member_presence])
def test_both_guards_share_one_membership_rule(guard):
    space = make_space()
    user, _ = make_member(space, f"shared-membership-{guard.__name__}", membership=False)

    with pytest.raises(MemberPresenceRequired):
        guard(user, space)


@pytest.mark.parametrize("guard", [require_active_member, require_active_member_presence])
def test_both_guards_share_one_waiver_rule(guard):
    space = make_space()
    MakerspaceWaiver.objects.create(
        makerspace=space, is_active=True, version=1, body="Be careful."
    )
    user, _ = make_member(space, f"shared-waiver-{guard.__name__}", accept=False)

    with pytest.raises(WaiverAcceptanceRequired):
        guard(user, space)


# --- the nine invocations that must not have moved ---------------------------------


@pytest.mark.parametrize(
    "module_path",
    [
        "apps.hardware_requests.self_checkout_views",
        "apps.hardware_requests.direct_loan_workflow",
        "apps.hardware_requests.public_views",
        "apps.bookings.views_public",
        "apps.machines.views_public_service",
        "apps.machines.views_public_printer_service",
    ],
)
def test_hardware_and_facility_surfaces_still_bind_the_presence_guard(module_path):
    """Asserts on the resolved function object, not on source text.

    Paired with `test_require_active_member_presence_still_requires_a_session`, which
    proves that object still demands a session, this is what stops the refactor from
    silently relaxing self-checkout, direct handout, hardware requests, bookings or the
    machine-service surfaces.
    """
    import importlib

    module = importlib.import_module(module_path)

    assert getattr(module, "require_active_member_presence", None) is (
        require_active_member_presence
    )
    assert not hasattr(module, "require_active_member")


def test_event_registration_binds_the_membership_only_guard():
    from apps.events import views_public

    assert views_public.require_active_member is require_active_member
    assert not hasattr(views_public, "require_active_member_presence")
