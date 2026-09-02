from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.events.models import Event, EventOrganizer
from apps.makerspaces.models import Makerspace
from apps.organizations.models import Organization


pytestmark = pytest.mark.django_db


def organization(public=True):
    return Organization.objects.create(
        name="Public Federation",
        slug="public-federation",
        description="Shared workshops",
        website="https://federation.example.test",
        contact_email="private@example.test",
        billing_email="billing@example.test",
        legal_name="Private Legal Name",
        registration_number="SECRET-1",
        public_profile_enabled=public,
    )


def host(slug, *, events_enabled=True, hidden=False):
    return Makerspace.objects.create(
        name=slug.title(),
        slug=slug,
        enabled_modules=["events"] if events_enabled else [],
        hidden_from_central_directory=hidden,
        # ck_makerspace_hidden_requires_domain: a makerspace hidden from the central
        # directory must be reachable on its own domain, or it would be unreachable.
        frontend_domain=f"{slug}.example.test" if hidden else None,
    )


def event(space, title, *, public=True, status=Event.Status.PUBLISHED, ended=False):
    starts = timezone.now() + timedelta(hours=1)
    if ended:
        starts = timezone.now() - timedelta(hours=2)
    return Event.objects.create(
        makerspace=space,
        title=title,
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
        is_public=public,
        status=status,
    )


def test_public_profile_flag_has_closed_and_open_sides_without_sensitive_fields():
    org = organization(public=False)
    url = reverse("public-organization-detail", kwargs={"slug": org.slug})

    assert APIClient().get(url).status_code == 404

    org.public_profile_enabled = True
    org.save(update_fields=["public_profile_enabled"])
    response = APIClient().get(url)

    assert response.status_code == 200
    assert response.data["name"] == org.name
    assert response.data["catalogue_links"]["events"].endswith("/events/")
    assert not {
        "contact_email", "billing_email", "legal_name", "registration_number"
    }.intersection(response.data)

    org.is_active = False
    org.save(update_fields=["is_active"])
    assert APIClient().get(url).status_code == 404


def test_public_event_catalogue_keeps_host_provenance_and_all_visibility_gates():
    org = organization()
    visible_host = host("visible-host", events_enabled=True)
    module_off = host("module-off", events_enabled=False)
    hidden_host = host("hidden-host", hidden=True)
    archived_host = host("archived-host")
    archived_host.archived_at = timezone.now()
    archived_host.save(update_fields=["archived_at"])

    included = event(visible_host, "Included")
    excluded = [
        event(visible_host, "Private", public=False),
        event(visible_host, "Draft", status=Event.Status.DRAFT),
        event(visible_host, "Ended", ended=True),
        event(module_off, "Module off"),
        event(hidden_host, "Hidden host"),
        event(archived_host, "Archived host"),
    ]
    for row in [included, *excluded]:
        EventOrganizer.objects.create(event=row, organization=org)

    response = APIClient().get(
        reverse("public-organization-events", kwargs={"slug": org.slug})
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["title"] == "Included"
    assert response.data["results"][0]["host"] == {
        "slug": visible_host.slug,
        "name": visible_host.name,
        "logo_url": None,
    }


def test_event_module_toggle_hides_without_deleting_organized_event():
    org = organization()
    space = host("toggle-host")
    organized = event(space, "Retained")
    EventOrganizer.objects.create(event=organized, organization=org)
    url = reverse("public-organization-events", kwargs={"slug": org.slug})

    assert APIClient().get(url).data["count"] == 1
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])
    assert APIClient().get(url).data["count"] == 0
    assert Event.objects.filter(pk=organized.pk).exists()
