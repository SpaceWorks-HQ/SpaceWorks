"""Structured logging configuration.

Production emits one JSON object per line so a log shipper can index by ``request_id``,
``logger`` or any ``extra=`` key without regex; local development keeps the plain
single-line format because a human is reading it. Both carry the request id from
``config.request_id`` so the two formats differ only in shape, never in content.

Named ``log_setup`` rather than ``logging`` on purpose: a module called ``config.logging``
is one careless ``sys.path`` entry away from shadowing the standard library.
"""
import json
import logging
from datetime import UTC, datetime

from config.request_id import get_request_id

# Attributes every LogRecord carries. Anything else on the record came from ``extra=`` and
# is worth surfacing as its own JSON key.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info", "thread",
        "threadName", "taskName", "request_id",
    }
)


class RequestIdFilter(logging.Filter):
    """Stamp the bound request id (or ``-``) on every record so formatters can rely on it."""

    def filter(self, record):
        record.request_id = get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or "-",
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def build_logging(level: str, *, json_output: bool) -> dict:
    formatter = "json" if json_output else "plain"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "config.log_setup.RequestIdFilter"},
        },
        "formatters": {
            "json": {"()": "config.log_setup.JsonFormatter"},
            "plain": {
                "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "filters": ["request_id"],
                "formatter": formatter,
            },
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            # Django's own request/security loggers are noisy at DEBUG; hold them at the
            # configured level but never below WARNING for the request logger, which
            # otherwise duplicates every 4xx the view already reported.
            "django": {"level": level, "propagate": True},
            "django.request": {"level": "WARNING", "propagate": True},
            "django.security": {"level": "WARNING", "propagate": True},
            "celery": {"level": level, "propagate": True},
            "apps": {"level": level, "propagate": True},
        },
    }
