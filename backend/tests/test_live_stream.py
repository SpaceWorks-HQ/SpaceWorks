"""Live-update hints: channel scoping, on-commit publishing, and the SSE endpoint's failure modes."""
import json

import pytest
from django.db import transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit import services as audit
from apps.operations import live
from apps.operations.views_live import subscribed_channels
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


class FakeRedis:
    def __init__(self):
        self.published = []

    def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))


@pytest.fixture
def fake_redis(monkeypatch, settings):
    settings.LIVE_REDIS_URL = "redis://fake:6379/0"
    client = FakeRedis()
    monkeypatch.setattr(live, "redis_client", lambda: client)
    return client


def test_channels_follow_rbac_scope():
    alpha, beta = make_space("live-alpha"), make_space("live-beta")
    manager = make_member("live-manager", alpha)
    member = make_user("live-member", access_status=User.AccessStatus.ACTIVE)
    root = make_user("live-root", role=User.Role.SUPERADMIN, is_superuser=True)

    assert subscribed_channels(manager) == [
        live.user_channel(manager.pk),
        live.makerspace_channel(alpha.pk),
    ]
    assert subscribed_channels(member) == [live.user_channel(member.pk)]
    root_channels = subscribed_channels(root)
    assert live.makerspace_channel(alpha.pk) in root_channels
    assert live.makerspace_channel(beta.pk) in root_channels


def test_audit_record_publishes_after_commit_only(fake_redis):
    space = make_space("live-commit")
    actor = make_member("live-actor", space)
    with transaction.atomic():
        audit.record(actor, "request.accepted", makerspace=space, target=space)
        assert fake_redis.published == []  # nothing until the transaction commits
    # pytest's django_db wraps the test in a transaction that never commits, so on_commit
    # callbacks are only observable through the captured-on-commit API.


def test_audit_record_publish_payload_carries_no_content(fake_redis, django_capture_on_commit_callbacks):
    space = make_space("live-payload")
    actor = make_member("live-payload-actor", space)
    with django_capture_on_commit_callbacks(execute=True):
        audit.record(
            actor, "request.issued", makerspace=space, target=space,
            meta={"requester_name": "Someone Private", "email": "p@example.com"},
        )
    channels = [channel for channel, _ in fake_redis.published]
    assert live.makerspace_channel(space.pk) in channels
    assert live.user_channel(actor.pk) in channels
    _, payload = fake_redis.published[0]
    assert payload["kind"] == "request.issued"
    assert payload["makerspace_id"] == space.pk
    assert payload["target_type"] == "makerspaces.makerspace"
    assert "Someone Private" not in json.dumps(payload)
    assert set(payload) == {"kind", "makerspace_id", "target_type", "target_id", "actor_id", "ts"}


def test_publish_is_a_no_op_without_redis(settings, django_capture_on_commit_callbacks):
    settings.LIVE_REDIS_URL = ""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    space = make_space("live-none")
    actor = make_member("live-none-actor", space)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        audit.record(actor, "request.rejected", makerspace=space, target=space)
    assert callbacks == []


def test_stream_requires_auth_and_reports_503_without_redis(settings, monkeypatch):
    settings.LIVE_REDIS_URL = ""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    url = reverse("live")
    assert APIClient().get(url).status_code in (401, 403)
    space = make_space("live-503")
    manager = make_member("live-503-manager", space)
    response = authenticated_client(manager).get(url, HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 503
    assert response["Content-Type"].startswith("application/json")


def test_stream_emits_events_from_the_subscribed_channels(settings, monkeypatch):
    settings.LIVE_REDIS_URL = "redis://fake:6379/0"
    settings.LIVE_MAX_STREAM_SECONDS = 1

    class FakePubSub:
        def __init__(self):
            self.channels = ()
            self.messages = []

        def subscribe(self, *channels):
            self.channels = channels
            self.messages = [{"type": "message", "data": b'{"kind":"request.accepted"}'}]

        def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
            return self.messages.pop(0) if self.messages else None

    class FakeClient:
        pubsub_instance = FakePubSub()

        def pubsub(self):
            return self.pubsub_instance

    monkeypatch.setattr(live, "redis_client", lambda: FakeClient())
    space = make_space("live-stream")
    manager = make_member("live-stream-manager", space)
    # Browsers ask for text/event-stream explicitly; DRF negotiation must not answer 406.
    response = authenticated_client(manager).get(reverse("live"), HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["X-Accel-Buffering"] == "no"
    body = b"".join(response.streaming_content).decode()
    assert body.startswith("retry: 5000\n\n")
    assert 'event: change\ndata: {"kind":"request.accepted"}\n\n' in body
    assert set(FakeClient.pubsub_instance.channels) == {
        live.user_channel(manager.pk), live.makerspace_channel(space.pk),
    }
