"""Per-request correlation id.

One id follows a request through every log line it emits and into every Celery task it
enqueues, so a support question ("what happened when I pressed Issue at 14:02?") can be
answered by one grep instead of by guessing at timestamps. The id is stored in a
``contextvars.ContextVar`` rather than on the request object because the log formatter and
Celery signal handlers have no request to hand.

The incoming ``X-Request-ID`` header is honoured only when it is short and plain ASCII: a
reverse proxy that already assigns ids should win, but a caller must not be able to inject
newlines or a kilobyte of junk into every log line.
"""
import contextvars
import re
import uuid

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "spaceworks_request_id", default=None
)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str) -> contextvars.Token:
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


def new_request_id() -> str:
    return uuid.uuid4().hex


def normalize_request_id(candidate: str | None) -> str:
    """Return the caller's id when it is safe to log, otherwise mint a fresh one."""
    if candidate and _VALID_REQUEST_ID.match(candidate):
        return candidate
    return new_request_id()


class RequestIdMiddleware:
    """Bind a request id for the duration of the request and echo it on the response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.request_id = request_id
        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response[REQUEST_ID_HEADER] = request_id
        return response
