"""The collaborative registration route must share the create budget but not the repair path.

`_collaborative_events()` deliberately includes events hosted by the member's OWN space, so
the same event is reachable through this route and through
`views_public.PublicEventRegistrationView`. With a throttle on only one of them, a caller
could register through the unthrottled route and never spend the configured budget.

Closing that cannot be allowed to close the waiver-repair path with it. DRF checks throttles
in `initial()`, before `post()` runs, so a 429 never reaches the `DuplicateRegistration`
handler where `_stamp_host_waiver` fixes a registration holding no acceptance -- and since
the create bucket is shared, the public route could exhaust it and strand a member at the
door with no way to repair their own row.
"""

import pytest
from django.urls import reverse
from django.core.cache import cache

from apps.events.models import EventRegistration
from tests.events.collab_helpers import (
    client_for,
    collaborate,
    make_event,
    make_member,
    make_space,
)

pytestmark = pytest.mark.django_db


def register_url(space, event):
    return reverse(
        "member-collaborative-event-register",
        kwargs={"makerspace_id": space.pk, "pk": event.pk},
    )


def exhaust(scope, user, limit=10):
    """Spend a member's whole bucket for `scope` without going through a view.

    Writing the throttle's own cache key is deliberate: driving the public route enough
    times to drain it would also create registrations, which changes which branch the
    route under test takes.
    """
    from rest_framework.throttling import ScopedRateThrottle

    throttle = ScopedRateThrottle()
    throttle.scope = scope
    throttle.rate = throttle.get_rate()
    throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
    key = throttle.cache_format % {"scope": scope, "ident": user.pk}
    from django.utils import timezone

    now = timezone.now().timestamp()
    cache.set(key, [now] * limit, throttle.duration)


def test_a_new_registration_spends_the_shared_create_budget():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    exhaust("event_register", member)

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 429


def test_a_retry_survives_an_exhausted_create_budget():
    """The repair path. This is the assertion the naive class-level throttle would break."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client = client_for(member)
    first = client.post(register_url(partner, event), {}, format="json")
    assert first.status_code == 201

    # Everything the member could have spent on creating registrations, gone -- including
    # through the public route, which shares this bucket.
    exhaust("event_register", member)

    retry = client.post(register_url(partner, event), {}, format="json")

    assert retry.status_code == 201, "a member must always be able to repair their own row"


def test_the_retry_budget_is_itself_bounded():
    """Not throttling retries at all would leave an unbounded authenticated write path."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client = client_for(member)
    assert client.post(register_url(partner, event), {}, format="json").status_code == 201
    exhaust("event_registration_retry", member, limit=30)

    retry = client.post(register_url(partner, event), {}, format="json")

    assert retry.status_code == 429


def test_the_create_budget_is_the_same_bucket_as_the_public_route():
    """One member, one create budget, whichever route they use.

    `exhaust()` above writes the key DRF's `ScopedRateThrottle` derives from
    (scope + authenticated user pk) -- which is precisely the key the public route uses --
    and `test_a_new_registration_spends_the_shared_create_budget` shows the collaborative
    route then 429s. That is the behavioural proof; this only pins the key DERIVATION,
    because a throttle emitting a different ident (`MemberPrincipalRateThrottle` prefixes
    `member:`) would silently create a second bucket and hand out the limit twice.
    """
    from apps.apiclients.throttling import (
        ClientTierRateThrottle,
        MemberPrincipalRateThrottle,
    )
    from apps.events.throttles import CollaborativeRegistrationThrottle
    from apps.events.views_member_events import MemberCollaborativeEventRegistrationView
    from apps.events.views_public import PublicEventRegistrationView

    assert MemberCollaborativeEventRegistrationView.throttle_classes == [
        CollaborativeRegistrationThrottle
    ]
    assert issubclass(CollaborativeRegistrationThrottle, ClientTierRateThrottle)
    assert not issubclass(CollaborativeRegistrationThrottle, MemberPrincipalRateThrottle)
    assert PublicEventRegistrationView.throttle_scope == "event_register"


def test_re_registering_after_cancelling_spends_the_CREATE_budget():
    """A cancelled row is not a repair, and treating it as one reopens the bypass.

    `services_registration.register()` REACTIVATES a cancelled registration as a fresh one
    rather than raising `DuplicateRegistration`, so it never reaches the waiver-repair
    handler. Counting it as a retry would let a member cancel and re-register indefinitely
    on the larger retry budget -- the create limit bypassed by a second route.
    """
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client = client_for(member)
    assert client.post(register_url(partner, event), {}, format="json").status_code == 201
    registration = EventRegistration.objects.get(event=event, member=member)
    EventRegistration.objects.filter(pk=registration.pk).update(
        status=EventRegistration.Status.CANCELLED
    )
    exhaust("event_register", member)

    again = client.post(register_url(partner, event), {}, format="json")

    assert again.status_code == 429


def test_an_unregistered_member_is_not_charged_the_retry_scope():
    """The branch is chosen by whether a registration exists, not by anything else."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    exhaust("event_registration_retry", member, limit=30)

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 201
    assert EventRegistration.objects.filter(event=event, member=member).exists()
