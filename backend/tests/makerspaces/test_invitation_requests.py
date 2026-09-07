"""Public invitation requests: throttled, honeypotted, PII-encrypted, and the staff queue."""
import pytest
from django.core.cache import cache
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.audit.models import AuditLog
from apps.encryption.crypto import is_envelope
from apps.makerspaces.models import InvitationRequest, MakerspaceRole, MembershipRequest
from tests.encryption.conftest import enabled_encryption
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "name": "Ada Lovelace",
    "email": "Ada@Example.test",
    "phone": "+15550100",
    "message": "I would love to join the electronics bench.",
}


def submit(space, payload=PAYLOAD, client=None):
    return (client or APIClient()).post(
        reverse("public-invitation-request", args=[space.slug]), payload, format="json"
    )


def test_public_submission_stores_a_pending_lead_and_audits_it():
    space = make_space("invite-req")

    response = submit(space)

    assert response.status_code == 202
    row = InvitationRequest.objects.get(makerspace=space)
    assert (row.name, row.email, row.phone) == ("Ada Lovelace", "ada@example.test", "+15550100")
    assert row.status == "pending"
    entry = AuditLog.objects.get(action="invitation_request.submitted")
    assert entry.meta == {"invitation_request_id": row.pk}
    assert entry.target_id == str(row.pk) and entry.makerspace_id == space.pk


def test_honeypot_gets_the_same_ack_and_stores_nothing():
    space = make_space("invite-honeypot")

    real = submit(space)
    trapped = submit(space, {**PAYLOAD, "website": "https://spam.example"})

    assert trapped.status_code == real.status_code == 202
    assert trapped.data == real.data
    assert InvitationRequest.objects.filter(makerspace=space).count() == 1
    assert AuditLog.objects.filter(action="invitation_request.submitted").count() == 1


def test_module_off_answers_404_and_bad_input_400():
    space = make_space("invite-off")
    assert submit(space, {"name": "", "email": "nope"}).status_code == 400
    disable_module(space, "membership")
    assert submit(space).status_code == 404
    assert not InvitationRequest.objects.exists()


def test_submission_is_throttled(settings, monkeypatch):
    space = make_space("invite-throttle")
    cache.clear()
    rest_settings = dict(settings.REST_FRAMEWORK)
    rates = {**rest_settings["DEFAULT_THROTTLE_RATES"], "public_invitation_request": "1/hour"}
    rest_settings["DEFAULT_THROTTLE_RATES"] = rates
    settings.REST_FRAMEWORK = rest_settings
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", rates)
    client = APIClient()

    assert submit(space, client=client).status_code == 202
    assert submit(space, client=client).status_code == 429
    assert InvitationRequest.objects.count() == 1


def test_pii_columns_are_envelopes_when_encryption_is_enabled():
    space = make_space("invite-encrypted")
    with enabled_encryption():
        assert submit(space).status_code == 202
        row = InvitationRequest.objects.get(makerspace=space)
        assert row.email == "ada@example.test"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, email, phone, message FROM makerspaces_invitationrequest WHERE id = %s",
                [row.pk],
            )
            name, email, phone, message = cursor.fetchone()
        assert all(is_envelope(value) for value in (name, email, phone))
        assert message == PAYLOAD["message"]


def test_staff_queue_invites_declines_and_is_scoped():
    space, other = make_space("invite-staff"), make_space("invite-staff-other")
    manager = make_member("invite-staff-mgr", space)
    client = authenticated_client(manager)
    stranger = authenticated_client(make_member("invite-staff-stranger", other))
    submit(space)
    submit(space, {**PAYLOAD, "email": "second@example.test"})
    first, second = InvitationRequest.objects.filter(makerspace=space).order_by("pk")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    list_url = reverse("admin-invitation-requests", args=[space.pk])

    assert stranger.get(list_url).status_code == 404
    listed = client.get(list_url, {"status": "pending"})
    assert listed.status_code == 200 and {row["id"] for row in listed.data} == {first.pk, second.pk}
    assert listed.data[0]["email"] in {"ada@example.test", "second@example.test"}

    invite_url = reverse("admin-invitation-request-invite", args=[first.pk])
    assert stranger.post(invite_url, {"role_id": role.pk}, format="json").status_code == 404
    invited = client.post(invite_url, {"role_id": role.pk}, format="json")
    assert invited.status_code == 200 and invited.data["status"] == "invited"
    invitation = MembershipRequest.objects.get(
        makerspace=space, invite_email="ada@example.test", state=MembershipRequest.State.INVITED
    )
    entry = AuditLog.objects.get(action="invitation_request.invited")
    assert entry.meta == {
        "invitation_request_id": first.pk,
        "membership_request_id": invitation.pk,
        "role_id": role.pk,
    }
    assert client.post(invite_url, {"role_id": role.pk}, format="json").status_code == 400

    declined = client.post(reverse("admin-invitation-request-decline", args=[second.pk]))
    assert declined.status_code == 200 and declined.data["status"] == "declined"
    second.refresh_from_db()
    assert second.handled_by == manager and second.handled_at is not None
    assert AuditLog.objects.filter(action="invitation_request.declined").count() == 1
