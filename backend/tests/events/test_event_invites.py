from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events.invites import create_invite, revoke_invite
from tests.events.collab_helpers import client_for, make_staff
from tests.events.ticketing_helpers import event_space, account, open_event, signup

pytestmark = pytest.mark.django_db


def test_invite_is_digest_only_email_bound_and_idempotent_retry_does_not_spend_use():
    space = event_space()
    staff, user = make_staff(space), account()
    event = open_event(space, "invite")
    invite, code = create_invite(event, actor=staff, email=user.email.upper())
    assert code not in str(invite.__dict__) and user.email not in str(invite.__dict__)
    assert signup(event, account("wrong"), invite_code=code).status_code == 404
    assert signup(event, user, invite_code=code).status_code == 201
    assert signup(event, user, invite_code=code).status_code == 201
    invite.refresh_from_db()
    assert invite.uses == 1
    assert AuditLog.objects.filter(action="event.invite_redeemed").count() == 1
    assert code not in str(list(AuditLog.objects.values_list("meta", flat=True)))


@pytest.mark.parametrize("state", ["unknown", "expired", "revoked", "exhausted", "wrong_event"])
def test_bad_invites_have_uniform_404_and_do_not_register(state):
    space = event_space()
    event = open_event(space, "invite")
    staff = make_staff(space)
    invite, code = create_invite(event, actor=staff)
    if state == "unknown":
        code = "unknown"
    elif state == "expired":
        invite.expires_at = timezone.now() - timedelta(seconds=1)
        invite.save(update_fields=["expires_at"])
    elif state == "revoked":
        revoke_invite(invite, actor=staff)
    elif state == "exhausted":
        assert signup(event, account("first"), invite_code=code).status_code == 201
    else:
        event = open_event(space, "invite")
    response = signup(event, account(), invite_code=code)
    assert response.status_code == 404
    assert not event.registrations.filter(member__username="attendee").exists()


def test_staff_invites_are_tenant_scoped_and_codes_are_returned_once():
    space, other = event_space(), event_space("other")
    staff, foreign = make_staff(space), make_staff(other)
    event = open_event(space, "invite")
    route = reverse("admin-event-invites", args=[event.pk])
    assert client_for(foreign).post(route, {}, format="json").status_code == 404
    created = client_for(staff).post(route, {"max_uses": 2}, format="json")
    assert created.status_code == 201 and created.data["code"]
    listed = client_for(staff).get(route)
    assert "code" not in listed.data["results"][0]
    assert "code_digest" not in listed.data["results"][0]
    revoke = reverse("admin-event-invite-revoke", args=[created.data["id"]])
    assert client_for(foreign).post(revoke, {}, format="json").status_code == 404
    assert client_for(staff).post(revoke, {}, format="json").status_code == 200
    assert AuditLog.objects.filter(action="event.invite_revoked", actor=staff).exists()


def test_failed_form_validation_does_not_consume_an_invite():
    space = event_space()
    event = open_event(space, "invite", custom_form=[{"id": "answer", "label": "Answer", "type": "short_text", "required": True, "options": []}])
    invite, code = create_invite(event, actor=make_staff(space))
    assert signup(event, account(), invite_code=code).status_code == 400
    invite.refresh_from_db()
    assert invite.uses == 0
