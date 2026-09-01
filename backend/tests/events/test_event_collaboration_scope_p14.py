"""Phase 3 -- the collaboration API's TWO tenant scopes, and who may manage what.

`origin_scope_routes` is keyed by route NAME, not HTTP method, and its model lookups read
`kwargs['pk']`. So host removal and collaborator response cannot share one generic detail
route: registering an accept route against the host's makerspace would 403 it from exactly
the collaborator's own custom domain that needs it, which is the whole feature.

Eligibility and discovery cases live in `test_event_collaboration_p14.py`.
"""

import pytest
from django.urls import resolve as resolve_url, reverse
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.events.models import EventCollaborator, EventRegistration
from apps.makerspaces import origin_scope
from tests.events.collab_helpers import (
    client_for,
    collaborate,
    make_event,
    make_member,
    make_space,
    make_staff,
)


def register_url(space, event):
    return reverse(
        "member-collaborative-event-register",
        kwargs={"makerspace_id": space.pk, "pk": event.pk},
    )

pytestmark = pytest.mark.django_db


# --- the two tenant scopes ----------------------------------------------------------


def _origin_target(url, method="post"):
    match = resolve_url(url)
    request = getattr(APIRequestFactory(), method)(url)
    request.resolver_match = match
    view = match.func.view_class(**match.func.view_initkwargs)
    view.kwargs = match.kwargs
    return origin_scope._target_makerspace_id(request, view)


def test_respond_resolves_to_the_collaborator_and_remove_to_the_host():
    """The defect this prevents is a 403 from the collaborator's own custom domain.

    `origin_scope_routes` is keyed by route NAME, not HTTP method, so host removal and
    collaborator response cannot share one generic detail route.
    """
    host, partner = make_space("host"), make_space("partner")
    row = collaborate(make_event(host, is_public=False), partner)

    respond = reverse("admin-event-collaboration-respond", kwargs={"pk": row.pk})
    remove = reverse("admin-event-collaboration-remove", kwargs={"pk": row.pk})

    assert _origin_target(respond) == partner.pk
    assert _origin_target(remove) == host.pk


def test_the_host_collaborator_list_resolves_to_the_host():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)

    url = reverse("admin-event-collaborators", kwargs={"pk": event.pk})

    assert _origin_target(url, method="get") == host.pk


# --- who may manage what ------------------------------------------------------------


def test_a_collaborators_staff_cannot_edit_the_hosts_event():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)

    response = client_for(make_staff(partner)).patch(
        reverse("admin-event-detail", kwargs={"pk": event.pk}),
        {"title": "Hijacked"},
        format="json",
    )

    assert response.status_code in (403, 404)
    event.refresh_from_db()
    assert event.title != "Hijacked"


def test_a_collaborators_staff_cannot_read_the_hosts_attendee_list():
    """Attendee rows carry names, emails and phone numbers belonging to the host."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)

    response = client_for(make_staff(partner)).get(
        reverse("admin-event-registration-list", kwargs={"pk": event.pk})
    )

    assert response.status_code in (403, 404)


def test_a_collaborator_accepts_its_own_invitation():
    host, partner = make_space("host"), make_space("partner")
    row = collaborate(
        make_event(host, is_public=False), partner,
        status=EventCollaborator.Status.INVITED,
    )

    response = client_for(make_staff(partner)).post(
        reverse("admin-event-collaboration-respond", kwargs={"pk": row.pk}),
        {"accept": True},
        format="json",
    )

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == EventCollaborator.Status.ACCEPTED


def test_a_host_cannot_accept_on_a_collaborators_behalf():
    """Otherwise invite->accept is a bare M2M wearing a status column."""
    host, partner = make_space("host"), make_space("partner")
    row = collaborate(
        make_event(host, is_public=False), partner,
        status=EventCollaborator.Status.INVITED,
    )

    response = client_for(make_staff(host)).post(
        reverse("admin-event-collaboration-respond", kwargs={"pk": row.pk}),
        {"accept": True},
        format="json",
    )

    assert response.status_code in (403, 404)
    row.refresh_from_db()
    assert row.status == EventCollaborator.Status.INVITED


# --- the four review findings, pinned ------------------------------------------------


def test_registration_requires_the_collaborators_current_waiver():
    """Collaboration relaxes `is_public` -- not the liability factor.

    `active_membership()` does not check the waiver on its own, so without the explicit
    guard a visiting member could register having accepted nothing.
    """
    from apps.makerspaces.models import MakerspaceWaiver

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    MakerspaceWaiver.objects.create(
        makerspace=partner, is_active=True, version=1, body="Be careful."
    )

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 403
    assert not EventRegistration.objects.filter(event=event).exists()


def test_an_archived_host_disappears_from_the_partner_inbox():
    """Archived is invisible outside /control/, and the inbox carries the host's event."""
    from django.utils import timezone
    from django.urls import reverse as rev

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False, title="Private planning")
    collaborate(event, partner, status=EventCollaborator.Status.INVITED)
    staff = make_staff(partner)
    url = rev("admin-event-collaboration-inbox", kwargs={"makerspace_id": partner.pk})
    assert len(client_for(staff).get(url).data) == 1

    host.archived_at = timezone.now()
    host.save(update_fields=["archived_at"])

    assert client_for(staff).get(url).data == []


def test_an_archived_hosts_invitation_cannot_still_be_accepted():
    """The read filter alone is not enough: the partner may already hold the row id."""
    from django.utils import timezone
    from django.urls import reverse as rev

    host, partner = make_space("host"), make_space("partner")
    row = collaborate(
        make_event(host, is_public=False), partner,
        status=EventCollaborator.Status.INVITED,
    )
    host.archived_at = timezone.now()
    host.save(update_fields=["archived_at"])

    response = client_for(make_staff(partner)).post(
        rev("admin-event-collaboration-respond", kwargs={"pk": row.pk}),
        {"accept": True},
        format="json",
    )

    assert response.status_code in (403, 404)
    row.refresh_from_db()
    assert row.status == EventCollaborator.Status.INVITED


def test_a_double_submit_reports_the_existing_registration_not_a_failure():
    """A lost response must not tell a member they are unregistered when they are not."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client = client_for(member)

    first = client.post(register_url(partner, event), {}, format="json")
    second = client.post(register_url(partner, event), {}, format="json")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.data["status"] == EventRegistration.Status.REGISTERED
    assert EventRegistration.objects.filter(event=event, member=member).count() == 1


def test_a_partner_that_uninstalls_events_cannot_be_registered_through():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    partner.enabled_modules = [k for k in partner.enabled_modules if k != "events"]
    partner.save(update_fields=["enabled_modules"])

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code in (400, 403, 404)
    assert not EventRegistration.objects.filter(event=event).exists()


def test_removing_one_collaborator_works_even_if_another_was_archived():
    """Removal must not fail because of an unrelated row.

    Rebuilding the invited set through `invite_collaborators` validated every remaining
    slug and rejected archived ones, so removing A 400'd merely because B had since been
    archived -- an advertised action failing for a reason the operator cannot see.
    """
    host, first, second = make_space("host"), make_space("first"), make_space("second")
    event = make_event(host, is_public=False)
    row_first = collaborate(event, first)
    collaborate(event, second)
    second.archived_at = timezone.now()
    second.save(update_fields=["archived_at"])

    response = client_for(make_staff(host)).post(
        reverse("admin-event-collaboration-remove", kwargs={"pk": row_first.pk}),
        {},
        format="json",
    )

    assert response.status_code == 204
    assert not EventCollaborator.objects.filter(pk=row_first.pk).exists()
    # The archived partner's row is untouched -- removal removed exactly what was asked.
    assert EventCollaborator.objects.filter(event=event, makerspace=second).exists()


def test_responding_to_an_already_removed_invitation_is_a_404_not_a_500():
    host, partner = make_space("host"), make_space("partner")
    row = collaborate(
        make_event(host, is_public=False), partner,
        status=EventCollaborator.Status.INVITED,
    )
    staff = make_staff(partner)
    url = reverse("admin-event-collaboration-respond", kwargs={"pk": row.pk})
    EventCollaborator.objects.filter(pk=row.pk).delete()

    response = client_for(staff).post(url, {"accept": True}, format="json")

    assert response.status_code == 404
