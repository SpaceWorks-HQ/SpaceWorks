"""Editions x every PUBLIC route of a hidden module (matrix R20, R21, B13, E14, M12, M17).

An edition hides a module's public surface and those routes answer 404 (MODULES.md
"Editions"). Each route here used to check only its module or feature -- which an
edition deliberately leaves untouched -- so an events-only box still lent tools, took
bookings and machine jobs, and a bookings-only box still served member event feeds.
Staff routes are unaffected and pinned in `test_editions.py`.
"""

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.events.services_calendar_feeds import issue_or_rotate_feed
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.module_install import uninstall_module
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def _public_routes(space):
    slug = space.slug
    token = uuid.uuid4()
    return {
        "tool evidence url": ("post", f"/api/v1/public/{slug}/tools/evidence-url"),
        "tool checkout": ("post", f"/api/v1/public/{slug}/tools/checkout"),
        "tool return": ("post", f"/api/v1/public/{slug}/tools/return"),
        "request submit": ("post", reverse("hardware_requests:request-submit", args=[slug])),
        "bookable spaces": ("get", reverse("public-bookable-space-list", args=[slug])),
        "space availability": ("get", reverse("public-space-availability", args=[slug, token])),
        "booking submit": ("post", reverse("public-booking-submit", args=[slug, token])),
        "machine-service submit": (
            "post", reverse("public-machine-service-request-submit", args=[slug]),
        ),
        "printer queues": ("get", reverse("public-printer-service-queues", args=[slug])),
        "printer pools": ("get", reverse("public-printer-service-pools", args=[slug])),
    }


EVENTS_EDITION_HIDDEN = (
    "tool evidence url", "tool checkout", "tool return", "request submit",
    "bookable spaces", "space availability", "booking submit",
    "machine-service submit", "printer queues", "printer pools",
)


@pytest.mark.parametrize("route", EVENTS_EDITION_HIDDEN)
def test_events_edition_404s_every_public_route_of_a_hidden_module(settings, route):
    space = make_space(f"combo-edition-{route.replace(' ', '-')}")
    client = authenticated_client(make_member(f"combo-edition-{route.replace(' ', '-')}", space))
    method, url = _public_routes(space)[route]

    settings.SPACEWORKS_EDITION = "events"
    response = getattr(client, method)(url, {}, format="json")

    assert response.status_code == 404, (route, response.status_code, getattr(response, "data", None))


@pytest.mark.parametrize("route", ("bookable spaces", "printer queues"))
def test_the_same_routes_answer_in_the_makerspace_edition(settings, route):
    """Control: the 404 above is the edition, not a broken route."""
    space = make_space(f"combo-edition-control-{route.replace(' ', '-')}")
    method, url = _public_routes(space)[route]
    if route == "printer queues":
        _printer_queue(space)

    settings.SPACEWORKS_EDITION = "makerspace"
    response = getattr(APIClient(), method)(url)

    assert response.status_code == 200, response.data


def test_bookings_edition_hides_the_member_event_calendar_feed(settings):
    space = make_space("combo-edition-ics")
    user = make_member("combo-edition-ics-member", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    _feed, raw = issue_or_rotate_feed(membership, actor=user)
    url = reverse(
        "public-event-calendar-feed", kwargs={"makerspace_slug": space.slug, "raw_token": raw}
    )

    settings.SPACEWORKS_EDITION = "makerspace"
    assert APIClient().get(url).status_code == 200
    settings.SPACEWORKS_EDITION = "bookings"
    assert APIClient().get(url).status_code == 404


def _printer_queue(space):
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    return ServiceQueue.objects.create(
        makerspace=space, machine_type=printer_type, name="Combo prints"
    )


def _print_job(space):
    requester = make_member(f"{space.slug}-requester", space)
    return MachineServiceRequest.objects.create(
        makerspace=space, queue=_printer_queue(space), requester=requester,
        requester_name=requester.username, title="Combo print",
        status=MachineServiceRequest.Status.PENDING,
    )


def test_print_status_lookup_follows_the_printing_module_and_the_edition(settings):
    """M12: a space that uninstalled `printing` stops publishing job status."""
    space = make_space("combo-print-status")
    job = _print_job(space)
    url = reverse("public-printer-service-status", args=[job.public_token])

    assert APIClient().get(url).status_code == 200
    settings.SPACEWORKS_EDITION = "events"
    assert APIClient().get(url).status_code == 404
    settings.SPACEWORKS_EDITION = "makerspace"
    uninstall_module(space, "printing")
    response = APIClient().get(url)
    assert response.status_code == 400
    assert "printing" in str(response.data)
