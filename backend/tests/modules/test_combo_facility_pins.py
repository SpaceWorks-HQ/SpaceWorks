"""bookings / machine_service x membership state x certifications over HTTP (matrix B2, M1).

The certification gate was pinned only at the service layer, and a revoked member was
pinned only for borrowing. These drive the real public endpoints.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.machines.models import Machine, MachineServiceRequest
from apps.makerspaces.models import MakerspaceMembership
from apps.presence import services as presence
from tests.machines import certification_helpers as cert
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def test_public_machine_service_submit_refuses_an_uncertified_member():
    """M1: the HTTP submit reaches the same fail-closed gate as the service layer."""
    space = cert._space("combo-cert-http")
    machine_type = cert._machine_type(space)
    cert._certification(space, machine_type, name="Laser induction")
    member, _membership = cert._member(space, "combo-cert-http-member")
    presence.start_session(member, space, 60)
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser 1")

    response = authenticated_client(member).post(
        reverse("public-machine-service-request-submit", args=[space.slug]),
        {"machine_id": machine.pk, "title": "Cut my sign"},
        format="json",
    )

    assert response.status_code == 403, response.data
    assert response.data["code"] == "certification_required"
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()


def test_a_revoked_member_cannot_self_book():
    """B2: a revoked membership is refused at the public booking endpoint."""
    space = cert._space("combo-booking-revoked", certifications=False)
    member, membership = cert._member(space, "combo-booking-revoked-member")
    presence.start_session(member, space, 60)
    room = cert._bookable(space)
    room.is_public = True
    room.save(update_fields=["is_public"])
    MakerspaceMembership.objects.filter(pk=membership.pk).update(status="revoked")
    start =timezone.now() + timedelta(days=1)
    response = authenticated_client(member).post(
        reverse("public-booking-submit", args=[space.slug, room.public_token]),
        {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()},
        format="json",
    )

    assert response.status_code == 403, response.data
    assert not Booking.objects.filter(space=room).exists()
