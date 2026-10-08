"""The anchor failure taxonomy is decided at the sink boundary, from REAL sink responses.

Each test drives the concrete ``HttpCollectorAnchorSink`` / ``ObjectStorageAnchorSink`` with
a provider answer (an HTTP status/body, an S3 error or object body) and asserts the typed
exception the sink raises. Mocking only an ``AnchorConflict`` would prove nothing: the
question is whether the sink keeps transport, configuration and invalid-evidence apart.
"""

import io
import json

import boto3
import pytest
import requests
from botocore.exceptions import EndpointConnectionError, NoCredentialsError
from botocore.stub import Stubber

from apps.audit.anchors import (
    AnchorConfigurationError,
    AnchorConflict,
    AnchorError,
    AnchorInvalidEvidence,
    AnchorReadBudget,
    AnchorReadBudgetExceeded,
    AnchorTransportError,
    HttpCollectorAnchorSink,
    ObjectStorageAnchorSink,
    configured_sink,
)

IDENTITY = ("deployment", "makerspace:1", "a" * 64, 3)
ROTATION_IDENTITY = ("deployment", "makerspace:1", "a" * 64, "b" * 64, 3)


class FakeResponse:
    def __init__(self, status, body=None, raw=None):
        self.status_code = status
        self._body, self._raw = body, raw

    def json(self):
        if self._raw is not None:
            return json.loads(self._raw)
        return self._body


@pytest.fixture
def http_sink(settings):
    settings.AUDIT_ATTESTATION_HTTP_URL = "https://collector.example/anchors"
    settings.AUDIT_ATTESTATION_HTTP_BEARER_TOKEN = "token"
    return HttpCollectorAnchorSink()


def _answer(monkeypatch, response=None, exc=None, calls=None):
    def fake_get(*_args, **_kwargs):
        if calls is not None:
            calls.append(1)
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr("apps.audit.anchors_http.requests.get", fake_get)


def _envelope(**payload_overrides):
    payload = {
        "deployment_id": IDENTITY[0],
        "scope": IDENTITY[1],
        "signer_fingerprint": IDENTITY[2],
        "batch_seq": IDENTITY[3],
        **payload_overrides,
    }
    return {"payload": payload, "anchored_at": "2026-10-09T00:00:00+00:00"}


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
def test_http_transient_status_is_transport(monkeypatch, http_sink, status):
    _answer(monkeypatch, FakeResponse(status))
    with pytest.raises(AnchorTransportError):
        http_sink.fetch(IDENTITY)


@pytest.mark.parametrize("status", [400, 401, 403, 405, 410])
def test_http_permanent_refusal_is_configuration(monkeypatch, http_sink, status):
    _answer(monkeypatch, FakeResponse(status))
    with pytest.raises(AnchorConfigurationError):
        http_sink.fetch(IDENTITY)
    with pytest.raises(AnchorConfigurationError):
        http_sink.fetch_rotation(ROTATION_IDENTITY)


@pytest.mark.parametrize(
    "exc", [requests.Timeout("slow"), requests.ConnectionError("down")]
)
def test_http_timeout_and_connection_failure_are_transport(monkeypatch, http_sink, exc):
    _answer(monkeypatch, exc=exc)
    with pytest.raises(AnchorTransportError):
        http_sink.fetch(IDENTITY)
    with pytest.raises(AnchorTransportError):
        http_sink.fetch_scope_head("deployment", "makerspace:1")


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(200, raw="{not json"),
        FakeResponse(200, body={"payload": {}}),  # missing identity: raw KeyError inside
        FakeResponse(200, body=_envelope(batch_seq="three")),  # ValueError inside
        FakeResponse(200, body=_envelope(batch_seq=None)),  # TypeError inside
        FakeResponse(200, body=["not", "an", "object"]),
    ],
)
def test_http_malformed_evidence_is_invalid_not_transport(monkeypatch, http_sink, response):
    _answer(monkeypatch, response)
    with pytest.raises(AnchorInvalidEvidence) as caught:
        http_sink.fetch(IDENTITY)
    assert not isinstance(caught.value, AnchorTransportError)


def test_http_identity_disagreement_stays_a_conflict(monkeypatch, http_sink):
    _answer(monkeypatch, FakeResponse(200, body=_envelope(batch_seq=99)))
    with pytest.raises(AnchorConflict):
        http_sink.fetch(IDENTITY)


def test_http_valid_point_read_and_404_keep_their_meaning(monkeypatch, http_sink):
    _answer(monkeypatch, FakeResponse(200, body=_envelope()))
    assert http_sink.fetch(IDENTITY)["payload"]["batch_seq"] == 3
    _answer(monkeypatch, FakeResponse(404))
    assert http_sink.fetch(IDENTITY) is None
    assert http_sink.fetch_rotation(ROTATION_IDENTITY) is None


def test_http_malformed_rotation_is_invalid_evidence(monkeypatch, http_sink):
    _answer(monkeypatch, FakeResponse(200, body={"payload": {"domain": "nope"}}))
    with pytest.raises(AnchorInvalidEvidence):
        http_sink.fetch_rotation(ROTATION_IDENTITY)


def test_http_scope_head_404_is_missing_evidence_not_retryable(monkeypatch, http_sink):
    _answer(monkeypatch, FakeResponse(404))
    with pytest.raises(AnchorInvalidEvidence) as caught:
        http_sink.fetch_scope_head("deployment", "makerspace:1")
    assert not isinstance(caught.value, AnchorTransportError)


def test_http_scope_head_malformed_is_conflict(monkeypatch, http_sink):
    _answer(monkeypatch, FakeResponse(200, body={"batch_seq": "x"}))
    with pytest.raises(AnchorConflict):
        http_sink.fetch_scope_head("deployment", "makerspace:1")


def test_http_settings_failures_are_configuration(settings):
    settings.AUDIT_ATTESTATION_HTTP_URL = "http://plain.example/anchors"
    settings.AUDIT_ATTESTATION_HTTP_BEARER_TOKEN = "token"
    with pytest.raises(AnchorConfigurationError):
        HttpCollectorAnchorSink()
    settings.AUDIT_ATTESTATION_HTTP_URL = "https://collector.example/anchors"
    settings.AUDIT_ATTESTATION_HTTP_BEARER_TOKEN = ""
    with pytest.raises(AnchorConfigurationError):
        HttpCollectorAnchorSink()


def test_unconfigured_backend_is_configuration_and_still_an_anchor_error(settings):
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = ""
    with pytest.raises(AnchorConfigurationError) as caught:
        configured_sink()
    assert isinstance(caught.value, AnchorError)  # existing broad callers still catch it


def test_http_budget_refuses_before_the_request(monkeypatch, settings):
    settings.AUDIT_ATTESTATION_HTTP_URL = "https://collector.example/anchors"
    settings.AUDIT_ATTESTATION_HTTP_BEARER_TOKEN = "token"
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "http"
    calls = []
    _answer(monkeypatch, FakeResponse(404), calls=calls)
    sink = configured_sink(read_budget=AnchorReadBudget(2))
    sink.fetch(IDENTITY)
    sink.fetch_rotation(ROTATION_IDENTITY)
    with pytest.raises(AnchorReadBudgetExceeded) as caught:
        sink.fetch(IDENTITY)
    assert len(calls) == 2
    assert not isinstance(caught.value, AnchorError)


# --- object storage: a real boto3 client, stubbed at the wire-response layer ---------


@pytest.fixture
def object_sink(settings, monkeypatch):
    settings.AUDIT_ATTESTATION_S3_BUCKET = "anchors"
    settings.AUDIT_ATTESTATION_RETENTION_DAYS = 1
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y"
    )
    stubber = Stubber(client)
    stubber.activate()
    sink = ObjectStorageAnchorSink(read_budget=None)
    monkeypatch.setattr(sink, "_client", lambda: client)
    sink.stubber = stubber
    return sink


def _body(value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return {"Body": io.BytesIO(raw)}


@pytest.mark.parametrize(
    "code,status,expected",
    [
        ("SlowDown", 503, AnchorTransportError),
        ("InternalError", 500, AnchorTransportError),
        ("RequestTimeout", 400, AnchorTransportError),
        ("AccessDenied", 403, AnchorConfigurationError),
        ("InvalidAccessKeyId", 403, AnchorConfigurationError),
        ("NoSuchBucket", 404, AnchorConfigurationError),
    ],
)
def test_object_service_errors_are_classified(object_sink, code, status, expected):
    object_sink.stubber.add_client_error(
        "get_object", service_error_code=code, http_status_code=status
    )
    with pytest.raises(expected):
        object_sink.fetch(IDENTITY)


def test_object_missing_key_is_absent(object_sink):
    object_sink.stubber.add_client_error(
        "get_object", service_error_code="NoSuchKey", http_status_code=404
    )
    assert object_sink.fetch(IDENTITY) is None


@pytest.mark.parametrize(
    "body",
    [b"\xff\xfe not utf-8", b"{truncated", {"payload": {}}, _envelope(batch_seq="x")],
)
def test_object_malformed_body_is_invalid_evidence(object_sink, body):
    object_sink.stubber.add_response("get_object", _body(body))
    with pytest.raises(AnchorInvalidEvidence) as caught:
        object_sink.fetch(IDENTITY)
    assert not isinstance(caught.value, AnchorTransportError)


def test_object_valid_body_round_trips(object_sink):
    object_sink.stubber.add_response("get_object", _body(_envelope()))
    assert object_sink.fetch(IDENTITY)["payload"]["scope"] == "makerspace:1"


def test_object_malformed_rotation_body_is_invalid_evidence(object_sink):
    object_sink.stubber.add_response("get_object", _body({"payload": {}}))
    with pytest.raises(AnchorInvalidEvidence):
        object_sink.fetch_rotation(ROTATION_IDENTITY)


def test_object_connection_and_credential_failures(object_sink, monkeypatch):
    def boom(exc):
        def raiser(**_kwargs):
            raise exc
        return raiser

    client = object_sink._client()
    monkeypatch.setattr(
        client, "get_object", boom(EndpointConnectionError(endpoint_url="https://s3"))
    )
    with pytest.raises(AnchorTransportError):
        object_sink.fetch(IDENTITY)
    monkeypatch.setattr(client, "get_object", boom(NoCredentialsError()))
    with pytest.raises(AnchorConfigurationError):
        object_sink.fetch(IDENTITY)


def test_object_settings_failures_are_configuration(settings):
    settings.AUDIT_ATTESTATION_S3_BUCKET = ""
    with pytest.raises(AnchorConfigurationError):
        ObjectStorageAnchorSink()
    settings.AUDIT_ATTESTATION_S3_BUCKET = "anchors"
    settings.AUDIT_ATTESTATION_RETENTION_DAYS = 1
    settings.AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE = "LOOSE"
    with pytest.raises(AnchorConfigurationError):
        ObjectStorageAnchorSink()


def _page(keys, token=None):
    page = {"Contents": [{"Key": key} for key in keys], "IsTruncated": bool(token)}
    if token:
        page["NextContinuationToken"] = token
    return page


def test_object_listing_pages_and_transition_reads_share_one_budget(object_sink):
    """Scope-head resolution: list pages, the head GET, transition list pages and the
    transition GETs all draw from the one attempt budget, refused before the provider call."""
    sink = object_sink
    prefix = sink._scope_directory("deployment", "makerspace:1") + "/"
    sink.stubber.add_response("list_objects_v2", _page([prefix + "a" * 64 + "/x.json"], "t1"))
    sink.stubber.add_response("list_objects_v2", _page([prefix + "a" * 64 + "/00000000000000000003.json"]))
    sink.stubber.add_response("get_object", _body(_envelope(merkle_root="00" * 32)))
    transitions = prefix + "transitions/"
    sink.stubber.add_response(
        "list_objects_v2",
        _page([transitions + f"00000000000000000003-{'a' * 64}-{'b' * 64}.json"], "t2"),
    )
    sink.read_budget = AnchorReadBudget(4)
    with pytest.raises(AnchorReadBudgetExceeded):
        sink.fetch_scope_head("deployment", "makerspace:1")
    assert sink.read_budget.used == 4
    # Exactly the four permitted operations reached the provider; the fifth (the
    # transition GET) was refused before the call, so nothing is left unconsumed.
    sink.stubber.assert_no_pending_responses()


def test_object_listing_without_budget_follows_every_page(object_sink):
    sink = object_sink
    prefix = sink._scope_directory("deployment", "makerspace:1") + "/"
    sink.stubber.add_response("list_objects_v2", _page([], "t1"))
    sink.stubber.add_response("list_objects_v2", _page([]))
    assert sink.fetch_scope_head("deployment", "makerspace:1") == (-1, None, None)
    assert prefix  # the prefix is the scope directory every page was asked for
    sink.stubber.assert_no_pending_responses()


def test_object_listing_service_failure_is_classified(object_sink):
    object_sink.stubber.add_client_error(
        "list_objects_v2", service_error_code="SlowDown", http_status_code=503
    )
    with pytest.raises(AnchorTransportError):
        object_sink.fetch_scope_head("deployment", "makerspace:1")
