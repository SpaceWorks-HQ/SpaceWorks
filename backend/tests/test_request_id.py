"""Request-id correlation: middleware, contextvar, Celery propagation."""
import logging

import pytest
from django.test import RequestFactory
from django.http import HttpResponse

from config import celery_signals
from config.request_id import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)


def _run(request):
    seen = {}

    def view(_request):
        seen["during"] = get_request_id()
        seen["attr"] = getattr(_request, "request_id", None)
        return HttpResponse("ok")

    response = RequestIdMiddleware(view)(request)
    return response, seen


def test_incoming_header_is_honoured_and_echoed():
    request = RequestFactory().get("/api/v1/health/", HTTP_X_REQUEST_ID="proxy-abc.123")
    response, seen = _run(request)
    assert seen["during"] == "proxy-abc.123"
    assert seen["attr"] == "proxy-abc.123"
    assert response[REQUEST_ID_HEADER] == "proxy-abc.123"
    # The binding is scoped to the request; nothing leaks into the caller's context.
    assert get_request_id() is None


@pytest.mark.parametrize(
    "bad",
    ["", "has space", "new\nline", "x" * 65, "quote\"", "semi;colon"],
)
def test_unsafe_header_values_are_replaced_with_a_fresh_id(bad):
    request = RequestFactory().get("/api/v1/health/", HTTP_X_REQUEST_ID=bad)
    response, seen = _run(request)
    minted = response[REQUEST_ID_HEADER]
    assert minted != bad
    assert len(minted) == 32 and all(c in "0123456789abcdef" for c in minted)
    assert seen["during"] == minted


def test_missing_header_mints_an_id():
    response, seen = _run(RequestFactory().get("/api/v1/health/"))
    assert response[REQUEST_ID_HEADER] == seen["during"]
    assert normalize_request_id(None) != normalize_request_id(None)


def test_middleware_unbinds_even_when_the_view_raises():
    def view(_request):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        RequestIdMiddleware(view)(RequestFactory().get("/"))
    assert get_request_id() is None


def test_celery_publish_header_and_worker_rebind():
    token = set_request_id("req-42")
    try:
        headers = {}
        celery_signals.propagate_request_id(headers=headers)
        assert headers[celery_signals.HEADER] == "req-42"
        # An explicit header already present wins (a retry re-publishes its own id).
        headers = {celery_signals.HEADER: "earlier"}
        celery_signals.propagate_request_id(headers=headers)
        assert headers[celery_signals.HEADER] == "earlier"
    finally:
        reset_request_id(token)

    class FakeRequest:
        headers = {celery_signals.HEADER: "worker-side"}

    class FakeTask:
        request = FakeRequest()

    assert get_request_id() is None
    celery_signals.bind_request_id(task=FakeTask)
    assert get_request_id() == "worker-side"
    celery_signals.unbind_request_id(task=FakeTask)
    assert get_request_id() is None


def test_publish_without_a_bound_id_adds_nothing():
    headers = {}
    celery_signals.propagate_request_id(headers=headers)
    assert headers == {}


def test_log_records_carry_the_bound_request_id(caplog):
    from config.log_setup import RequestIdFilter

    logger = logging.getLogger("tests.request_id")
    logger.addFilter(RequestIdFilter())
    try:
        token = set_request_id("rid-log")
        try:
            with caplog.at_level(logging.INFO, logger="tests.request_id"):
                logger.info("hello")
        finally:
            reset_request_id(token)
        assert caplog.records[-1].request_id == "rid-log"
    finally:
        logger.filters.clear()
