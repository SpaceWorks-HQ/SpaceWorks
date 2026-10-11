import pytest
from django.urls import reverse

from apps.events import services
from tests.events.collab_helpers import client_for, make_staff
from tests.events.ticketing_helpers import account, event_space, open_event, signup

pytestmark = pytest.mark.django_db


def test_account_ticket_ownership_survives_audience_edits_without_opening_member_history():
    space = event_space()
    staff, user, outsider = make_staff(space), account(), account("outsider")
    event = open_event(space)
    assert signup(event, user).status_code == 201
    registration = event.registrations.get()
    services.update_event(event, actor=staff, registration_audience="members")
    qr = reverse("member-event-checkin-qr", args=[space.pk, registration.pk])
    cancel = reverse("member-event-registration-cancel", args=[space.pk, registration.pk])
    assert client_for(outsider).get(qr).status_code == 404
    assert client_for(outsider).post(cancel, {}, format="json").status_code == 404
    assert client_for(user).get(qr).status_code == 200
    assert client_for(user).post(cancel, {}, format="json").status_code == 200


def test_account_only_ticket_does_not_authorize_a_member_default_registration():
    space = event_space(membership=True)
    from apps.events.models import EventRegistration
    event = open_event(space, "members")
    user = account()
    registration = EventRegistration.objects.create(event=event, member=user, name=user.username, email=user.email, phone=user.phone)
    assert client_for(user).get(reverse("member-event-checkin-qr", args=[space.pk, registration.pk])).status_code == 404
