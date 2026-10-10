"""The SSE stream under a broken or vanishing Redis (cloud lane).

`test_live_stream.py` pins "no Redis -> 503" and the happy stream. These are the three
cases in between: a `LIVE_REDIS_URL` that cannot even be parsed (was a 500 from the view
and from every publish), Redis refusing the subscription, and Redis dying while a stream
is open (the generator used to raise mid-body). Every exit closes the pubsub connection.
"""

import pytest
from django.urls import reverse

from apps.operations import live
from apps.operations.views_live import _event_stream
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


class _PubSub:
    def __init__(self, messages=(), fail_after=None):
        self.messages = list(messages)
        self.fail_after = fail_after
        self.calls = 0
        self.closed = False

    def subscribe(self, *channels):
        self.channels = channels

    def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ConnectionError("redis went away")
        return self.messages.pop(0) if self.messages else None

    def close(self):
        self.closed = True


def _manager(slug):
    space = make_space(slug)
    return authenticated_client(make_member(f"{slug}-manager", space))


def test_an_unparseable_live_redis_url_is_unavailable_not_500(settings):
    settings.LIVE_REDIS_URL = "notaredis://::bad::"
    assert live.redis_client() is None

    response = _manager("live-bad-url").get(reverse("live"), HTTP_ACCEPT="text/event-stream")

    assert response.status_code == 503
    assert response["Content-Type"].startswith("application/json")


def test_publishing_with_an_unparseable_url_is_a_quiet_no_op(settings):
    settings.LIVE_REDIS_URL = "notaredis://::bad::"
    assert live.publish(live.makerspace_channel(1), "{}") is False


def test_redis_refusing_the_subscription_is_a_temporary_503(settings, monkeypatch):
    settings.LIVE_REDIS_URL = "redis://fake:6379/0"

    class Client:
        def pubsub(self):
            raise ConnectionError("connection refused")

    monkeypatch.setattr(live, "redis_client", lambda: Client())

    response = _manager("live-refused").get(reverse("live"), HTTP_ACCEPT="text/event-stream")

    assert response.status_code == 503
    assert "temporarily" in response.json()["detail"]


def test_redis_dying_mid_stream_ends_the_stream_cleanly_and_closes_it():
    pubsub = _PubSub(
        messages=[{"type": "message", "data": b'{"kind":"request.accepted"}'}], fail_after=1
    )

    frames = list(_event_stream(pubsub, deadline=float("inf")))  # must not raise

    assert frames[0] == "retry: 5000\n\n"
    assert 'event: change\ndata: {"kind":"request.accepted"}\n\n' in frames
    assert pubsub.closed is True


def test_the_deadline_closes_the_connection():
    pubsub = _PubSub()

    frames = list(_event_stream(pubsub, deadline=0))

    assert frames == ["retry: 5000\n\n"]
    assert pubsub.closed is True


def test_a_client_disconnect_closes_the_connection():
    pubsub = _PubSub(messages=[{"type": "message", "data": b"{}"}])
    stream = _event_stream(pubsub, deadline=float("inf"))

    next(stream)
    next(stream)
    stream.close()  # what the WSGI server does when the browser goes away

    assert pubsub.closed is True


def test_a_close_that_itself_fails_does_not_escape():
    class Fragile(_PubSub):
        def close(self):
            raise ConnectionError("already gone")

    assert list(_event_stream(Fragile(), deadline=0)) == ["retry: 5000\n\n"]
