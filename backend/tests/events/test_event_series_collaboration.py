from datetime import time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events import services_series, services_series_collaboration
from apps.events.models import (
    EventCollaborator,
    EventRegistration,
    EventSeries,
    EventSeriesCollaborator,
)
from apps.makerspaces.models import (
    DEFAULT_ENABLED_MODULES,
    Makerspace,
    MakerspaceMembership,
)

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted({*DEFAULT_ENABLED_MODULES, "events"}),
    )


def make_manager(space, username):
    actor = User.objects.create_user(username=username)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def make_series(space, actor):
    return services_series.create_series(
        makerspace=space,
        actor=actor,
        title="Partner workshop",
        recurrence_timezone="UTC",
        dtstart_local_date=(timezone.now() + timedelta(days=1)).date(),
        dtstart_local_time=time(10),
        recurrence_rule="FREQ=DAILY",
        duration_minutes=60,
    )


def test_acceptance_projects_once_to_current_and_future_occurrences(monkeypatch):
    host, visitor = make_space("series-host"), make_space("series-visitor")
    host_manager = make_manager(host, "series-host-manager")
    visitor_manager = make_manager(visitor, "series-visitor-manager")
    series, initial = make_series(host, host_manager)
    rows = services_series_collaboration.invite_collaborators(
        series, actor=host_manager, slugs=[visitor.slug, visitor.slug]
    )
    invitation = rows.get()

    inbox = client_for(visitor_manager).get(
        reverse(
            "admin-event-series-collaboration-inbox",
            kwargs={"makerspace_id": visitor.pk},
        )
    )
    services_series_collaboration.respond(
        invitation, actor=visitor_manager, accept=True
    )

    assert inbox.status_code == 200
    assert [row["id"] for row in inbox.data] == [invitation.pk]
    assert EventCollaborator.objects.filter(
        source_series_collaboration=invitation,
        status=EventCollaborator.Status.ACCEPTED,
    ).count() == len(initial)

    advanced = timezone.now() + timedelta(days=30)
    monkeypatch.setattr(services_series.timezone, "now", lambda: advanced)
    _series, added = services_series.extend_series(series, actor=host_manager)
    assert added
    assert EventCollaborator.objects.filter(
        source_series_collaboration=invitation
    ).count() == len(initial) + len(added)


def test_removal_drops_projections_without_erasing_registration_history():
    host, visitor = make_space("series-remove-host"), make_space("series-remove-visitor")
    host_manager = make_manager(host, "series-remove-host-manager")
    visitor_manager = make_manager(visitor, "series-remove-visitor-manager")
    series, occurrences = make_series(host, host_manager)
    invitation = services_series_collaboration.invite_collaborators(
        series, actor=host_manager, slugs=[visitor.slug]
    ).get()
    services_series_collaboration.respond(
        invitation, actor=visitor_manager, accept=True
    )
    registration = EventRegistration.objects.create(
        event=occurrences[0],
        name="Visitor",
        email="series-visitor@example.test",
        phone="123",
        registered_via_makerspace=visitor,
    )

    services_series_collaboration.remove_collaborator(
        invitation.pk, actor=host_manager
    )

    assert not EventCollaborator.objects.filter(
        source_series_collaboration_id=invitation.pk
    ).exists()
    assert EventRegistration.objects.filter(pk=registration.pk).exists()


def test_projected_occurrence_collaborators_must_be_managed_on_series():
    host, visitor = make_space("series-projected-host"), make_space("series-projected-visitor")
    host_manager = make_manager(host, "series-projected-host-manager")
    visitor_manager = make_manager(visitor, "series-projected-visitor-manager")
    series, occurrences = make_series(host, host_manager)
    invitation = services_series_collaboration.invite_collaborators(
        series, actor=host_manager, slugs=[visitor.slug]
    ).get()
    services_series_collaboration.respond(
        invitation, actor=visitor_manager, accept=True
    )

    response = client_for(host_manager).put(
        reverse("admin-event-collaborators", kwargs={"pk": occurrences[0].pk}),
        {"slugs": []},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "use_series_collaborators"


def test_series_detail_does_not_leak_across_tenants():
    host, outsider = make_space("series-private-host"), make_space("series-outsider")
    host_manager = make_manager(host, "series-private-host-manager")
    outsider_manager = make_manager(outsider, "series-outsider-manager")
    series, _occurrences = make_series(host, host_manager)

    response = client_for(outsider_manager).get(
        reverse("admin-event-series-detail", kwargs={"pk": series.pk})
    )

    assert response.status_code == 404
    assert EventSeriesCollaborator.objects.count() == 0
