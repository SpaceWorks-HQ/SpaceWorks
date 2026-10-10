"""Bounded token exchange failures are sanitized and release the HTTP connection."""

import io
import json
from types import SimpleNamespace

import pytest
import requests
from urllib3.exceptions import ProtocolError

from apps.accounts import oidc_browser_http as http


class Response:
    def __init__(self, payload, status=200, raw=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw = raw or io.BytesIO(json.dumps(payload).encode())
        self.closed = False

    def close(self):
        self.closed = True


def exchange(monkeypatch, response):
    def post(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        assert kwargs["timeout"] > 0
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(http.requests, "post", post)
    return http.exchange_code(
        SimpleNamespace(client_id="client"), {"token_endpoint": "https://id.example/token"},
        code="private-code", redirect_uri="https://app.example/callback", code_verifier="pkce",
    )


@pytest.mark.parametrize("response", [
    Response({"error": "server_error"}, 500), Response({}, 503), Response([], 200),
    Response(None), Response("oops"), Response({}, headers={"Content-Length": "bad"}),
    requests.Timeout("private-code"), requests.ConnectionError("private-code"),
])
def test_unavailable_token_endpoint_is_sanitized_and_closed(monkeypatch, response):
    with pytest.raises(http.OidcProviderUnavailable) as raised:
        exchange(monkeypatch, response)
    assert "private-code" not in str(raised.value)
    if isinstance(response, Response):
        assert response.closed


@pytest.mark.parametrize("failure", [OSError("private-code"), ProtocolError("private-code")])
def test_mid_body_failure_is_unavailable(monkeypatch, failure):
    class BrokenBody:
        def read(self, size):
            raise failure

    response = Response({}, raw=BrokenBody())
    with pytest.raises(http.OidcProviderUnavailable):
        exchange(monkeypatch, response)
    assert response.closed


@pytest.mark.parametrize("payload,status", [
    ({"error": "invalid_grant"}, 400), ({}, 200), ({"id_token": " "}, 200),
    ({"id_token": []}, 200), ({"id_token": "x" * 16385}, 200),
])
def test_invalid_grant_or_token_is_rejected_and_closed(monkeypatch, payload, status):
    response = Response(payload, status)
    with pytest.raises(http.OidcTokenRejected):
        exchange(monkeypatch, response)
    assert response.closed


def test_valid_token_is_returned_and_response_closed(monkeypatch):
    response = Response({"id_token": " token "})
    assert exchange(monkeypatch, response) == "token"
    assert response.closed


def test_body_read_is_part_of_the_elapsed_time_budget(monkeypatch, settings):
    settings.OIDC_HTTP_TIMEOUT_SECONDS = 3
    ticks = iter([0, 1, 4])
    monkeypatch.setattr(http.time, "monotonic", lambda: next(ticks))
    response = Response({"id_token": "token"})
    with pytest.raises(http.OidcProviderUnavailable):
        exchange(monkeypatch, response)
    assert response.closed
