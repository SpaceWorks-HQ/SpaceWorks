import json
import logging

from django.conf import settings

from config.log_setup import JsonFormatter, RequestIdFilter, build_logging


def _record(**extra):
    record = logging.LogRecord(
        name="apps.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="issued %s", args=("drill",), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    RequestIdFilter().filter(record)
    return record


def test_json_formatter_emits_one_object_with_extras_and_request_id():
    line = JsonFormatter().format(_record(audit_event_uuid="u-1", makerspace_id=7))
    payload = json.loads(line)
    assert payload["message"] == "issued drill"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "apps.test"
    assert payload["request_id"] == "-"
    assert payload["audit_event_uuid"] == "u-1"
    assert payload["makerspace_id"] == 7
    assert payload["ts"].endswith("+00:00")
    assert "\n" not in line


def test_json_formatter_serialises_non_json_extras_and_exceptions():
    try:
        raise ValueError("bad")
    except ValueError:
        import sys
        record = _record(weird=object())
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert payload["weird"].startswith("<object object")
    assert "ValueError: bad" in payload["exception"]


def test_build_logging_selects_formatter_and_levels():
    config = build_logging("DEBUG", json_output=True)
    assert config["handlers"]["console"]["formatter"] == "json"
    assert config["root"]["level"] == "DEBUG"
    assert config["loggers"]["django.request"]["level"] == "WARNING"
    plain = build_logging("INFO", json_output=False)
    assert plain["handlers"]["console"]["formatter"] == "plain"
    assert "%(request_id)s" in plain["formatters"]["plain"]["format"]


def test_settings_wire_the_logging_config():
    assert settings.LOGGING["handlers"]["console"]["filters"] == ["request_id"]
    assert "config.request_id.RequestIdMiddleware" in settings.MIDDLEWARE
    # The recovery gate stays first and the calendar-feed redactor second; correlation
    # binds immediately after them so every later layer logs with an id.
    assert settings.MIDDLEWARE.index("config.request_id.RequestIdMiddleware") == 2
