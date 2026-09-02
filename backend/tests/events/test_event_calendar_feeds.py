from urllib.parse import urlsplit

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.data_export.classification import OMITTED_MODELS
from apps.events.middleware import redact_calendar_feed_uri
from apps.events.models import MemberCalendarFeed
from tests.events.checkin_helpers import client_for, make_event, make_member, make_space, register


pytestmark = pytest.mark.django_db


def manage_url(space):
    return reverse("member-event-calendar-feed", kwargs={"makerspace_id": space.pk})


def path_from_absolute(value):
    return urlsplit(value).path


@override_settings(API_CLIENT_AUTH_REQUIRED=True)
def test_feed_is_one_time_bearer_and_rotation_and_revocation_are_immediate():
    space = make_space("calendar-feed")
    member = make_member(space, "feed-member")
    register(make_event(space, "Private feed event", is_public=False), member)
    client = client_for(member)

    assert client.post(
        manage_url(space), {"confirm_bearer_risk": False}, format="json"
    ).status_code == 400
    issued = client.post(manage_url(space), {"confirm_bearer_risk": True}, format="json")
    first_path = path_from_absolute(issued.data["feed_url"])
    state = client.get(manage_url(space))
    audit_count = AuditLog.objects.count()
    first = APIClient().get(first_path)
    assert AuditLog.objects.count() == audit_count
    rotated = client.post(manage_url(space), {"confirm_bearer_risk": True}, format="json")
    second_path = path_from_absolute(rotated.data["feed_url"])

    assert issued.status_code == 200
    assert state.data["enabled"] is True and "feed_url" not in state.data
    assert first.status_code == 200 and b"Private feed event" in first.content
    assert first_path != second_path
    assert APIClient().get(first_path).status_code == 404
    assert APIClient().get(second_path).status_code == 200
    assert client.delete(manage_url(space)).status_code == 204
    assert APIClient().get(second_path).status_code == 404
    assert set(AuditLog.objects.values_list("action", flat=True)) >= {
        "event.calendar_feed_created", "event.calendar_feed_rotated",
        "event.calendar_feed_revoked",
    }


def test_feed_persists_only_a_digest_and_never_puts_raw_token_in_audit():
    space = make_space("calendar-feed-storage")
    member = make_member(space, "feed-storage-member")
    response = client_for(member).post(
        manage_url(space), {"confirm_bearer_risk": True}, format="json"
    )
    raw_token = path_from_absolute(response.data["feed_url"]).rsplit("/", 1)[-1][:-4]
    feed = MemberCalendarFeed.objects.get(membership__user=member)

    assert len(bytes(feed.token_digest)) == 32
    assert raw_token not in bytes(feed.token_digest).hex()
    assert raw_token not in str(AuditLog.objects.filter(target_id=str(feed.pk)).values("meta"))
    assert "events.MemberCalendarFeed" in OMITTED_MODELS


def test_feed_is_tenant_bound_module_gated_and_malformed_tokens_are_uniform_404():
    space = make_space("calendar-feed-gates")
    other = make_space("calendar-feed-other")
    member = make_member(space, "feed-gate-member")
    issued = client_for(member).post(
        manage_url(space), {"confirm_bearer_risk": True}, format="json"
    )
    path = path_from_absolute(issued.data["feed_url"])
    raw_token = path.rsplit("/", 1)[-1][:-4]
    wrong_tenant = reverse("public-event-calendar-feed", kwargs={
        "makerspace_slug": other.slug, "raw_token": raw_token,
    })

    assert APIClient().get(wrong_tenant).status_code == 404
    assert APIClient().get(path.replace(raw_token, "not-a-token")).status_code == 404
    member.access_status = "suspended"
    member.save(update_fields=("access_status",))
    assert APIClient().get(path).status_code == 404
    member.access_status = "active"
    member.save(update_fields=("access_status",))
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=("enabled_modules",))
    assert APIClient().get(path).status_code == 404
    assert client_for(member).get(manage_url(space)).status_code == 400


def test_bearer_token_is_redacted_from_request_line_text():
    value = "/api/v1/public/space/event-calendar/secret-token.ics?refresh=1"
    redacted = redact_calendar_feed_uri(value)
    assert redacted == "/api/v1/public/space/event-calendar/[redacted].ics?refresh=1"
    assert "secret-token" not in redacted
