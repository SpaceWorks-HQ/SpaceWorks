"""Health HTTP contracts and bearer metrics remain stable during provider failures."""

import pytest
from rest_framework.test import APIClient

from apps.operations import live
from apps.operations.views_live import LiveStreamView
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path", ["/api/v1/health/", "/api/v1/health/readiness/"])
def test_invalid_bearer_on_a_probe_returns_401(path):
    assert APIClient().get(path, HTTP_AUTHORIZATION="Bearer invalid").status_code == 401


def test_metrics_bearer_survives_broker_outage(settings, monkeypatch):
    settings.METRICS_TOKEN = "metrics-test-token"
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_BROKER_URL = "redis://broker:6379"

    def unavailable(*args, **kwargs):
        raise ConnectionError("broker secret")

    monkeypatch.setattr("redis.Redis.from_url", unavailable)
    response = APIClient().get("/api/v1/metrics/", HTTP_AUTHORIZATION="Bearer metrics-test-token")
    assert response.status_code == 200
    assert "spaceworks_celery_queue_length{" not in response.content.decode()
    assert "broker secret" not in response.content.decode()


def test_live_broker_fallback_and_eager_suppression(settings):
    settings.LIVE_REDIS_URL = ""
    settings.CELERY_BROKER_URL = "redis://broker:6379"
    settings.CELERY_TASK_ALWAYS_EAGER = False
    assert live.live_redis_url() == "redis://broker:6379"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    assert live.live_redis_url() == ""
    settings.LIVE_REDIS_URL = "redis://dedicated:6379"
    assert live.live_redis_url() == "redis://dedicated:6379"


def test_failed_subscription_closes_the_allocated_pubsub(monkeypatch):
    closed = []

    class PubSub:
        def subscribe(self, *channels):
            raise ConnectionError("lost")

        def close(self):
            closed.append(True)

    class Client:
        def pubsub(self):
            return PubSub()

    monkeypatch.setattr(live, "redis_client", lambda: Client())
    space = make_space("live-subscribe-close")
    user = make_member("live-subscribe-close-user", space)
    response = authenticated_client(user).get("/api/v1/live/", HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 503
    assert closed == [True]
