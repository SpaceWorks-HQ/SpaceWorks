import re


_FEED_PATH = re.compile(
    r"(/api/v1/public/[^/]+/event-calendar/)[^/?]+(\.ics(?:\?.*)?)$"
)
_FEED_BEARER_PATH = re.compile(
    r"^/api/v1/public/[^/]+/event-calendar/[^/]+\.ics$"
)


def is_calendar_feed_bearer_path(value):
    return bool(_FEED_BEARER_PATH.fullmatch(value or ""))


def redact_calendar_feed_uri(value):
    return _FEED_PATH.sub(r"\1[redacted]\2", value or "")


class CalendarFeedLogRedactionMiddleware:
    """Remove bearer feed tokens from WSGI/Gunicorn request-line logging."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_uri = request.META.get("RAW_URI")
        if raw_uri:
            request.META["RAW_URI"] = redact_calendar_feed_uri(raw_uri)
        feed_path = request.path_info if is_calendar_feed_bearer_path(request.path_info) else None
        try:
            return self.get_response(request)
        finally:
            # Resolution and the view need the real token. Access/error logging happens
            # after the response, so replace every request-line source only on unwind.
            if feed_path:
                redacted = redact_calendar_feed_uri(feed_path)
                request.path = redacted
                request.path_info = redacted
                request.META["PATH_INFO"] = redacted
