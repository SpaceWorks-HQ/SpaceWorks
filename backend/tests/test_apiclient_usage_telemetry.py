import fnmatch
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from django.conf import settings as django_settings
from django.db.models.query import QuerySet
from django.test import RequestFactory, override_settings
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from apps.apiclients import telemetry
from apps.apiclients.models import ApiClient as ApiClientModel
from apps.apiclients.tasks import flush_api_client_usage_task
from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from tests.return_helpers import make_product, make_space

pytestmark = pytest.mark.django_db

ORIGIN = "https://usage.example.test"
PROTECTED_PREFIXES = ["/api/public/", "/api/v1/public/"]


class FakeRedis:
    def __init__(self, *, fail=False):
        self.hashes = {}
        self.expiries = {}
        self.fail = fail

    def pipeline(self, transaction=False):
        if self.fail:
            raise ConnectionError("redis unavailable")
        return self

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
        return self

    def expire(self, key, seconds):
        self.expiries[key] = seconds
        return self

    def execute(self):
        return []

    def scan_iter(self, match):
        return iter([key for key in self.hashes if fnmatch.fnmatch(key, match)])

    def rename(self, key, new_key):
        # Modelled because the flusher relies on it: reading and then deleting a bucket
        # would drop an observation written between the two calls.
        if key not in self.hashes:
            raise KeyError(key)
        self.hashes[new_key] = self.hashes.pop(key)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)


def _space_and_client(slug, *, client_type="server"):
    makerspace = make_space(slug)
    makerspace.public_inventory_enabled = True
    makerspace.enabled_modules = ["public_inventory"]
    makerspace.save(update_fields=["public_inventory_enabled", "enabled_modules"])
    make_product(makerspace, name=f"{slug} Product")
    api_client, secret = ApiClientModel.issue(
        label=f"{slug} client",
        makerspace=makerspace,
        allowed_origins=[ORIGIN],
        client_type=client_type,
    )
    return makerspace, api_client, secret


def _signed_headers(api_client, secret, path, **extra):
    timestamp = str(int(time.time()))
    message = b"\n".join([b"GET", path.encode(), timestamp.encode(), b""])
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": api_client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_ORIGIN": ORIGIN,
        **extra,
    }


def _url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/inventory/"


SIGNED_SETTINGS = override_settings(
    API_CLIENT_AUTH_REQUIRED=True,
    APICLIENT_REQUIRE_NONCE=False,
    HMAC_PROTECTED_PATH_PREFIXES=PROTECTED_PREFIXES,
)


@SIGNED_SETTINGS
def test_signed_request_flushes_closed_bucket_with_one_bulk_update(monkeypatch):
    observed_at = datetime(2026, 8, 19, 10, 4, 30, tzinfo=UTC)
    clock = [observed_at]
    fake = FakeRedis()
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: fake)
    monkeypatch.setattr(telemetry.timezone, "now", lambda: clock[0])
    makerspace, api_client, secret = _space_and_client("usage-flush")

    response = APIClient().get(
        _url(makerspace),
        REMOTE_ADDR="198.51.100.24",
        **_signed_headers(api_client, secret, _url(makerspace)),
    )
    calls = []
    real_bulk_update = QuerySet.bulk_update

    def track_bulk_update(queryset, objects, fields, **kwargs):
        if queryset.model is ApiClientModel:
            calls.append((list(objects), list(fields)))
        return real_bulk_update(queryset, objects, fields, **kwargs)

    monkeypatch.setattr(QuerySet, "bulk_update", track_bulk_update)
    bucket = telemetry.bucket_key(telemetry.SIGNED_KIND, observed_at)
    assert fake.expiries[bucket] == telemetry.BUCKET_TTL_SECONDS
    clock[0] += timedelta(minutes=1)
    updated = flush_api_client_usage_task()

    api_client.refresh_from_db()
    assert response.status_code == 200
    assert updated == 1
    assert len(calls) == 1
    assert api_client.last_seen_at == observed_at
    assert api_client.last_seen_ip == "198.51.100.24"


@SIGNED_SETTINGS
def test_current_minute_bucket_is_not_consumed(monkeypatch):
    now = datetime(2026, 8, 19, 10, 4, 30, tzinfo=UTC)
    fake = FakeRedis()
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: fake)
    monkeypatch.setattr(telemetry.timezone, "now", lambda: now)
    makerspace, api_client, secret = _space_and_client("usage-open")

    response = APIClient().get(
        _url(makerspace),
        **_signed_headers(api_client, secret, _url(makerspace)),
    )
    assert flush_api_client_usage_task() == 0

    api_client.refresh_from_db()
    assert response.status_code == 200
    assert api_client.last_seen_at is None
    assert telemetry.bucket_key(telemetry.SIGNED_KIND, now) in fake.hashes


def test_late_older_bucket_cannot_rewind_last_seen(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: fake)
    makerspace, api_client, _secret = _space_and_client("usage-monotonic")
    request = RequestFactory().get(_url(makerspace), REMOTE_ADDR="198.51.100.30")
    newer = datetime(2026, 8, 19, 11, 5, 20, tzinfo=UTC)
    older = newer - timedelta(minutes=3)

    monkeypatch.setattr(telemetry.timezone, "now", lambda: newer)
    telemetry.record_signed_client_observation(request, api_client)
    telemetry.flush_usage_observations(now=newer + timedelta(minutes=1), redis_client=fake)
    monkeypatch.setattr(telemetry.timezone, "now", lambda: older)
    telemetry.record_signed_client_observation(request, api_client)
    telemetry.flush_usage_observations(now=newer + timedelta(minutes=2), redis_client=fake)

    api_client.refresh_from_db()
    assert api_client.last_seen_at == newer
    assert api_client.last_seen_ip == "198.51.100.30"


@SIGNED_SETTINGS
def test_redis_write_failure_does_not_change_response(monkeypatch, caplog):
    makerspace, api_client, secret = _space_and_client("usage-redis-failure")
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: FakeRedis(fail=True))

    response = APIClient().get(
        _url(makerspace),
        **_signed_headers(api_client, secret, _url(makerspace)),
    )

    assert response.status_code == 200
    assert "usage telemetry Redis write failed" in caplog.text


@SIGNED_SETTINGS
def test_telemetry_write_adds_no_request_query(monkeypatch, django_assert_num_queries):
    makerspace, api_client, secret = _space_and_client("usage-query-budget")
    path = _url(makerspace)
    client = APIClient()
    real_recorder = telemetry.record_signed_client_observation
    monkeypatch.setattr(telemetry, "record_signed_client_observation", lambda *_args: None)
    from django.test.utils import CaptureQueriesContext
    from django.db import connection

    with CaptureQueriesContext(connection) as baseline:
        assert client.get(path, **_signed_headers(api_client, secret, path)).status_code == 200
    monkeypatch.setattr(telemetry, "record_signed_client_observation", real_recorder)
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: FakeRedis())

    with django_assert_num_queries(len(baseline)):
        assert client.get(path, **_signed_headers(api_client, secret, path)).status_code == 200


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    HMAC_PROTECTED_PATH_PREFIXES=PROTECTED_PREFIXES,
)
def test_forgeable_browser_id_uses_only_browser_namespace(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: fake)
    makerspace, api_client, _secret = _space_and_client(
        "usage-browser", client_type="browser"
    )

    response = APIClient().get(
        _url(makerspace),
        HTTP_X_CLIENT_ID=api_client.client_id,
        HTTP_ORIGIN=ORIGIN,
    )

    assert response.status_code == 200
    assert not list(fake.scan_iter(f"{telemetry.KEY_PREFIX}:signed:*"))
    assert list(fake.scan_iter(f"{telemetry.KEY_PREFIX}:browser:*"))


@SIGNED_SETTINGS
def test_untrusted_x_forwarded_for_is_not_stored(monkeypatch, settings):
    fake = FakeRedis()
    monkeypatch.setattr(telemetry, "get_redis_client", lambda: fake)
    settings.REST_FRAMEWORK = {**django_settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    settings.AXES_IPWARE_PROXY_COUNT = 0
    api_settings.reload()
    try:
        makerspace, api_client, secret = _space_and_client("usage-untrusted-xff")
        response = APIClient().get(
            _url(makerspace),
            REMOTE_ADDR="192.0.2.80",
            HTTP_X_FORWARDED_FOR="203.0.113.99",
            **_signed_headers(api_client, secret, _url(makerspace)),
        )
        key = next(iter(fake.scan_iter(f"{telemetry.KEY_PREFIX}:signed:*")))
        payload = json.loads(fake.hgetall(key)[api_client.client_id])
    finally:
        api_settings.reload()

    assert response.status_code == 200
    assert payload["resolved_ip"] == "192.0.2.80"


def test_usage_flush_is_registered_in_both_schedulers():
    task = "apps.apiclients.tasks.flush_api_client_usage_task"
    assert django_settings.CELERY_BEAT_SCHEDULE["flush-api-client-usage"]["task"] == task
    assert ("flush-api-client-usage", task, 1) in SCHEDULED_TASKS
