from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.events.models import Event, EventOrganizer
from apps.events.services_organizers import replace_organizers
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.organizations.models import Organization, OrganizationMembership


pytestmark = pytest.mark.django_db


def user(slug):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )


def client(actor, **headers):
    result = APIClient()
    result.force_authenticate(actor)
    result.defaults.update(headers)
    return result


def setup_event():
    space = Makerspace.objects.create(
        name="Organizer Venue",
        slug="organizer-venue",
        enabled_modules=["events"],
    )
    actor = user("event-manager")
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name="Event manager",
        slug="event-manager",
        granted_actions=[rbac.Action.MANAGE_EVENTS],
    )
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=actor,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    start = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=space,
        title="Managed event",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )
    return space, event, actor


def test_replace_organizers_is_action_scoped_atomic_and_audited():
    space, event, actor = setup_event()
    organization = Organization.objects.create(name="Event Guild", slug="event-guild")
    OrganizationMembership.objects.create(organization=organization, user=actor)
    url = reverse("admin-event-organizers", kwargs={"pk": event.pk})

    response = client(actor).put(
        url, {"organization_ids": [organization.pk]}, format="json"
    )

    assert response.status_code == 200
    assert response.data["organizers"] == [
        {"id": organization.pk, "slug": organization.slug, "name": organization.name}
    ]
    link = EventOrganizer.objects.get(event=event, organization=organization)
    assert link.created_by == actor
    audit = AuditLog.objects.get(action="event.organizers_updated")
    assert audit.makerspace_id == space.pk
    assert audit.meta["organization_ids"] == [organization.pk]
    event.refresh_from_db()
    assert event.makerspace_id == space.pk


def test_assignment_requires_active_membership_in_each_new_organization():
    _space, event, actor = setup_event()
    organization = Organization.objects.create(name="Unrelated Org", slug="unrelated-org")

    response = client(actor).put(
        reverse("admin-event-organizers", kwargs={"pk": event.pk}),
        {"organization_ids": [organization.pk]},
        format="json",
    )

    assert response.status_code == 403
    assert not EventOrganizer.objects.filter(event=event).exists()
    assert not AuditLog.objects.filter(action="event.organizers_updated").exists()


def test_module_off_refuses_mutation_but_retains_bridge():
    space, event, actor = setup_event()
    organization = Organization.objects.create(name="Retained Org", slug="retained-org")
    OrganizationMembership.objects.create(organization=organization, user=actor)
    link = EventOrganizer.objects.create(event=event, organization=organization)
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])

    response = client(actor).put(
        reverse("admin-event-organizers", kwargs={"pk": event.pk}),
        {"organization_ids": []},
        format="json",
    )

    assert response.status_code == 400
    assert EventOrganizer.objects.filter(pk=link.pk).exists()


def test_makerspace_custom_origin_cannot_call_global_organization_admin():
    space, _event, actor = setup_event()
    organization = Organization.objects.create(name="Origin Org", slug="origin-org")
    OrganizationMembership.objects.create(organization=organization, user=actor)
    space.frontend_domain = "organizer-venue.example.test"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save(update_fields=["frontend_domain", "frontend_domain_status"])

    response = client(actor, HTTP_ORIGIN="https://organizer-venue.example.test").get(
        reverse("admin-organization-list")
    )

    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_concurrent_replacements_leave_one_complete_organizer_set():
    _space, event, actor = setup_event()
    organizations = [
        Organization.objects.create(name=f"Race Org {number}", slug=f"race-org-{number}")
        for number in (1, 2)
    ]
    for organization in organizations:
        OrganizationMembership.objects.create(organization=organization, user=actor)
    gate = Barrier(2)

    def replace(organization_id):
        close_old_connections()
        gate.wait()
        try:
            replace_organizers(
                Event.objects.get(pk=event.pk),
                actor=User.objects.get(pk=actor.pk),
                organization_ids=[organization_id],
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(replace, [organization.pk for organization in organizations]))

    final_ids = set(
        EventOrganizer.objects.filter(event=event).values_list("organization_id", flat=True)
    )
    assert final_ids in ({organizations[0].pk}, {organizations[1].pk})
    assert AuditLog.objects.filter(action="event.organizers_updated").count() == 2
