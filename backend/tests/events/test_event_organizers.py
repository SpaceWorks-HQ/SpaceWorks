from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.events import notifications
from apps.events.models import Event, EventOrganizer, EventRegistration
from apps.events.serializers_collaborators import CollaborativeEventSerializer
from apps.events.serializers_public import PublicEventSerializer
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.operations.reports_events import build_event_attendance
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)


pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def make_user(slug, **values):
    values.setdefault("access_status", User.AccessStatus.ACTIVE)
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        **values,
    )


def make_event(space, title="Organized event"):
    start = timezone.now() + timedelta(hours=1)
    return Event.objects.create(
        makerspace=space,
        title=title,
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        status=Event.Status.PUBLISHED,
        is_public=True,
    )


def make_org(slug):
    return Organization.objects.create(name=slug.title(), slug=slug)


def link(organization, makerspace):
    return OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=makerspace,
        relationship=OrganizationMakerspace.Relationship.AFFILIATE,
    )


def grant(organization, user, actions):
    return OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        granted_actions=actions,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def detail_url(event):
    return reverse("admin-event-detail", kwargs={"pk": event.pk})


def test_unlinked_organizer_can_manage_only_its_exact_event():
    venue, linked_space = make_space("org-event-venue"), make_space("org-home")
    event = make_event(venue)
    other = make_event(venue, "Not organized")
    organization, actor = make_org("event-builders"), make_user("org-editor")
    link(organization, linked_space)
    grant(organization, actor, [rbac.Action.MANAGE_EVENTS])
    EventOrganizer.objects.create(event=event, organization=organization)
    registration = EventRegistration.objects.create(
        event=event, name="Organizer guest", email="organizer@example.test", phone="1"
    )
    event.registration_requires_approval = True
    event.save(update_fields=["registration_requires_approval"])
    pending = EventRegistration.objects.create(
        event=event, name="Pending guest", email="pending-organizer@example.test",
        phone="1", status=EventRegistration.Status.PENDING_APPROVAL,
    )
    other_registration = EventRegistration.objects.create(
        event=other, name="Other guest", email="other@example.test", phone="1"
    )

    loaded = client_for(actor).get(detail_url(event))
    edited = client_for(actor).patch(
        detail_url(event), {"title": "Edited by organizer"}, format="json"
    )
    attended = client_for(actor).post(
        reverse(
            "admin-event-registration-mark-attended",
            kwargs={"pk": registration.pk},
        ),
        {},
        format="json",
    )
    approved = client_for(actor).post(
        reverse("admin-event-registration-approve", kwargs={"pk": pending.pk}),
        {},
        format="json",
    )

    assert loaded.status_code == 200
    assert edited.status_code == 200
    assert attended.status_code == 200
    assert approved.status_code == 200
    assert client_for(actor).get(detail_url(other)).status_code == 404
    assert client_for(actor).post(
        reverse(
            "admin-event-registration-mark-attended",
            kwargs={"pk": other_registration.pk},
        ),
        {},
        format="json",
    ).status_code == 404
    assert rbac.resolve_scope(actor) == set()
    assert not rbac.is_space_manager_identity(actor, venue.pk)
    assert not rbac.can(actor, rbac.Action.MANAGE_EVENTS, venue.pk)


@pytest.mark.parametrize("organizes,actions", [(False, ["manage_events"]), (True, [])])
def test_non_organizer_or_membership_without_action_cannot_edit(organizes, actions):
    venue, event = make_space(f"denied-{organizes}"), None
    event = make_event(venue)
    organization = make_org(f"denied-org-{organizes}")
    actor = make_user(f"denied-user-{organizes}")
    grant(organization, actor, actions)
    if organizes:
        EventOrganizer.objects.create(event=event, organization=organization)

    assert client_for(actor).patch(
        detail_url(event), {"title": "Denied"}, format="json"
    ).status_code == 404


def test_archived_venue_disables_organizer_authority():
    venue, event = make_space("archived-organizer-venue"), None
    event = make_event(venue)
    organization, actor = make_org("archived-organizer"), make_user("archived-editor")
    grant(organization, actor, [rbac.Action.MANAGE_EVENTS])
    EventOrganizer.objects.create(event=event, organization=organization)
    venue.archived_at = timezone.now()
    venue.save(update_fields=["archived_at"])

    assert client_for(actor).get(detail_url(event)).status_code == 404


@pytest.mark.parametrize("blocked_by", ["membership", "organization"])
def test_inactive_organization_authority_grants_nothing(blocked_by):
    venue, event = make_space(f"inactive-{blocked_by}-venue"), None
    event = make_event(venue)
    organization = make_org(f"inactive-{blocked_by}-org")
    actor = make_user(f"inactive-{blocked_by}-editor")
    membership = grant(organization, actor, [rbac.Action.MANAGE_EVENTS])
    EventOrganizer.objects.create(event=event, organization=organization)
    if blocked_by == "membership":
        membership.status = OrganizationMembership.Status.SUSPENDED
        membership.save(update_fields=["status"])
    else:
        organization.is_active = False
        organization.save(update_fields=["is_active"])

    assert client_for(actor).get(detail_url(event)).status_code == 404


def test_registration_notifications_fan_out_once_and_isolate_failure(monkeypatch):
    venue = make_space("notification-venue")
    spaces = [make_space(f"notification-{index}") for index in range(3)]
    event = make_event(venue)
    registration = EventRegistration.objects.create(
        event=event, name="Guest", email="guest@example.test", phone="1"
    )
    first, second = make_org("notification-first"), make_org("notification-second")
    EventOrganizer.objects.create(event=event, organization=first)
    EventOrganizer.objects.create(event=event, organization=second)
    for organization, makerspace in (
        (first, venue),
        (first, spaces[0]),
        (first, spaces[1]),
        (second, spaces[1]),
        (second, spaces[2]),
    ):
        link(organization, makerspace)

    attempts, rendered = [], []

    def fake_render(makerspace, *args):
        rendered.append(makerspace.pk)
        return {"subject": makerspace.slug, "text_body": makerspace.slug}

    def fake_delivery(makerspace, *, build, **kwargs):
        attempts.append(makerspace.pk)
        if makerspace == spaces[1]:
            raise RuntimeError("isolated delivery failure")
        build()
        return object()

    monkeypatch.setattr(notifications, "render", fake_render)
    monkeypatch.setattr(notifications, "staff_emails_for_feature", lambda *a, **k: ())
    monkeypatch.setattr(notifications, "notify_lifecycle", fake_delivery)

    notifications.notify_event_lifecycle(
        event, "registration_created", registration.pk, sync=True
    )

    expected = {venue.pk, *(space.pk for space in spaces)}
    assert set(attempts) == expected
    assert len(attempts) == len(expected)
    assert set(rendered) == expected - {spaces[1].pk}


def test_serializers_expose_organizers_without_changing_the_host():
    venue, event = make_space("serializer-venue"), None
    event = make_event(venue)
    organizations = [make_org("alpha-org"), make_org("beta-org")]
    for organization in organizations:
        EventOrganizer.objects.create(event=event, organization=organization)
    event = Event.objects.prefetch_related("organizers__organization").get(pk=event.pk)

    public = PublicEventSerializer(event).data
    collaborative = CollaborativeEventSerializer(event).data
    expected = {
        (organization.slug, organization.name) for organization in organizations
    }

    assert {(row["slug"], row["name"]) for row in public["organizers"]} == expected
    assert {
        (row["slug"], row["name"]) for row in collaborative["organizers"]
    } == expected
    assert collaborative["host_name"] == venue.name
    assert collaborative["host_slug"] == venue.slug


def test_event_report_appends_attribution_without_multiplying_figures():
    venue, event = make_space("report-organizer-venue"), None
    event = make_event(venue)
    for slug in ("report-alpha", "report-beta"):
        EventOrganizer.objects.create(event=event, organization=make_org(slug))
    EventRegistration.objects.create(
        event=event, name="One", email="one@example.test", phone="1"
    )
    EventRegistration.objects.create(
        event=event,
        name="Two",
        email="two@example.test",
        phone="2",
        status=EventRegistration.Status.ATTENDED,
    )

    report = build_event_attendance(venue.pk)
    row = report.records[0]

    assert report.field_order[-1] == "organizers"
    assert (row["registrations"], row["confirmed"]) == (2, 2)
    assert row["organizers"] == "Report-Alpha (report-alpha); Report-Beta (report-beta)"


@pytest.mark.django_db(transaction=True)
def test_purge_uses_host_scope_and_preserves_global_organization_rows(monkeypatch):
    actor = make_user(
        "organizer-purge-root",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    venue, linked_space = make_space("purge-venue"), make_space("purge-org-link")
    event, organization = make_event(venue), make_org("purge-organization")
    member = make_user("purge-org-member")
    membership = grant(organization, member, [rbac.Action.MANAGE_EVENTS])
    link(organization, linked_space)
    organizer = EventOrganizer.objects.create(event=event, organization=organization)
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    monkeypatch.setattr(lifecycle, "_delete_public_image_keys", lambda keys: None)

    lifecycle.purge(lifecycle.archive(linked_space, actor), actor)

    assert EventOrganizer.objects.filter(pk=organizer.pk).exists()
    assert Organization.objects.filter(pk=organization.pk).exists()
    assert OrganizationMembership.objects.filter(pk=membership.pk).exists()

    lifecycle.purge(lifecycle.archive(venue, actor), actor)

    assert not EventOrganizer.objects.filter(pk=organizer.pk).exists()
    assert Organization.objects.filter(pk=organization.pk).exists()
    assert OrganizationMembership.objects.filter(pk=membership.pk).exists()


def test_organized_events_are_discoverable_without_venue_authority():
    """Per-event authority needs a surface, or it is only reachable by guessing an id.

    The venue's own event list stays denied -- organizer authority confers nothing over the
    venue -- so this endpoint lists exactly the events the organizer predicate matches.
    """
    venue, home = make_space("organized-list-venue"), make_space("organized-list-home")
    organized = make_event(venue, "Organized")
    make_event(venue, "Someone else's")
    organization, actor = make_org("organized-list-org"), make_user("organized-list-user")
    link(organization, home)
    grant(organization, actor, [rbac.Action.MANAGE_EVENTS])
    EventOrganizer.objects.create(event=organized, organization=organization)

    # A second organization organizing the SAME event: the row must not be duplicated and
    # its registration counts must not double, which a join-based predicate would do.
    second_org = make_org("organized-list-org-two")
    link(second_org, home)
    grant(second_org, actor, [rbac.Action.MANAGE_EVENTS])
    EventOrganizer.objects.create(event=organized, organization=second_org)
    EventRegistration.objects.create(
        event=organized, name="Counted once", email="once@example.test", phone="1"
    )

    response = client_for(actor).get(reverse("admin-organized-event-list"))

    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [organized.pk]
    counts = response.data["results"][0]["registration_counts"]
    assert counts["registered"] == 1, counts

    # The venue's own list is still refused: this surface adds discovery, not authority.
    venue_list = client_for(actor).get(
        reverse("admin-event-list-create", kwargs={"makerspace_id": venue.pk})
    )
    assert venue_list.status_code in (403, 404)


def test_a_deactivated_organization_stops_receiving_registration_notifications():
    """is_active is a kill switch, and a registration notification carries member PII.

    Leaving the fan-out running after deactivation would keep sending a registrant's name to
    an organization that has been switched off.
    """
    venue, org_space = make_space("notify-venue"), make_space("notify-org-space")
    event = make_event(venue)
    organization = make_org("notify-org")
    link(organization, org_space)
    EventOrganizer.objects.create(event=event, organization=organization)
    registration = EventRegistration.objects.create(
        event=event, name="Notify guest", email="notify@example.test", phone="1"
    )

    delivered = []
    original = notifications._notify_makerspace

    def record(event_id, makerspace, *args, **kwargs):
        delivered.append(makerspace.pk)
        return None

    notifications._notify_makerspace = record
    try:
        notifications.notify_event_lifecycle(
            event, "event.registration_created", registration_id=registration.pk
        )
        assert org_space.pk in delivered

        delivered.clear()
        Organization.objects.filter(pk=organization.pk).update(is_active=False)
        notifications.notify_event_lifecycle(
            event, "event.registration_created", registration_id=registration.pk
        )
        assert org_space.pk not in delivered
    finally:
        notifications._notify_makerspace = original
