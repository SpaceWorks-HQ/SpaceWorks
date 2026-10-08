"""Readiness and metrics probes in their unhappy states, over HTTP (cloud lane).

The readiness checks are unit-tested in `tests/backup/test_host_readiness_h1a.py`; nothing
asserted what an orchestrator actually SEES when one fails. A load balancer keys on the
status code, so a failed check must be a 503 with a JSON body, and the PII-key check must
not escape as a 500. Metrics: the documented `Authorization: Bearer` form, and an
unreachable broker that must empty the queue gauge rather than fail the whole scrape.
"""

import pytest
from rest_framework.test import APIClient

from apps.backup import host_readiness

pytestmark = pytest.mark.django_db

READY = "/api/v1/health/readiness/"
METRICS = "/api/v1/metrics/"


def test_a_failed_host_check_is_a_503_with_a_reason(monkeypatch):
    def not_ready(path):
        raise host_readiness.HostReadinessError("restore marker state does not admit backend")

    monkeypatch.setattr(host_readiness, "assert_host_ready", not_ready)

    response = APIClient().get(READY)

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "restore marker" in response.json()["detail"]


def test_unavailable_pii_keys_are_a_503_not_a_500(monkeypatch):
    from apps.encryption import readiness
    from apps.encryption.crypto import PiiUnavailable

    monkeypatch.setattr(host_readiness, "assert_host_ready", lambda path: None)

    def keys_gone(**kwargs):
        raise PiiUnavailable()

    monkeypatch.setattr(readiness, "assert_ready", keys_gone)

    response = APIClient().get(READY)

    assert response.status_code == 503


def test_liveness_needs_no_dependency_beyond_the_process():
    assert APIClient().get("/api/v1/health/").json() == {"status": "ok"}


def test_metrics_accept_the_documented_bearer_form(settings):
    settings.METRICS_TOKEN = "s3cret"
    settings.CELERY_TASK_ALWAYS_EAGER = True

    response = APIClient().get(METRICS, HTTP_AUTHORIZATION="Bearer s3cret")

    assert response.status_code == 200
    assert "# TYPE spaceworks_hardware_requests gauge" in response.content.decode()


def test_an_unreachable_broker_empties_the_queue_gauge_without_failing(settings):
    settings.METRICS_TOKEN = "s3cret"
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_BROKER_URL = "redis://127.0.0.1:1/0"  # nothing listens on port 1

    response = APIClient().get(METRICS, HTTP_AUTHORIZATION="Bearer s3cret")

    body = response.content.decode()
    assert response.status_code == 200
    assert "# TYPE spaceworks_celery_queue_length gauge" in body
    assert "spaceworks_celery_queue_length{" not in body
