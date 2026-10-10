import pytest
from django.core.exceptions import ValidationError

from apps.makerspaces.profile_validation import (
    COUNTRY_CODES, WEEKDAYS, default_timezone, validate_country,
    validate_opening_hours, validate_timezone,
)


@pytest.mark.parametrize("value", ["UTC", "Asia/Kolkata", "America/New_York", "Australia/Lord_Howe"])
def test_iana_zones_are_accepted(value):
    validate_timezone(value)


@pytest.mark.parametrize("value", ["Not/AZone", "../UTC", "", None, "GMT+5:30"])
def test_unknown_zones_are_rejected(value):
    with pytest.raises(ValidationError):
        validate_timezone(value)


def test_default_uses_deployment_timezone(settings):
    settings.TIME_ZONE = "Asia/Kolkata"
    assert default_timezone() == "Asia/Kolkata"


def test_complete_country_allowlist_and_blank():
    assert len(COUNTRY_CODES) == len(set(COUNTRY_CODES)) == 249
    for code in (*COUNTRY_CODES, ""):
        validate_country(code)


@pytest.mark.parametrize("value", ["ZZ", "USA", "in", "UK", "12"])
def test_invalid_countries_are_rejected(value):
    with pytest.raises(ValidationError):
        validate_country(value)


@pytest.mark.parametrize("intervals", [
    [{"start": "9:00", "end": "12:00"}], [{"start": "24:00", "end": "24:00"}],
    [{"start": "10:00", "end": "09:00"}], [{"start": "10:00", "end": "10:00"}],
    [{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}],
    [{"start": "13:00", "end": "14:00"}, {"start": "09:00", "end": "12:00"}],
    [{"start": "09:00", "end": "12:00", "actor_id": 1}],
    [{"start": True, "end": "12:00"}], "closed", [{}],
    [{"start": "0\u0669:00", "end": "12:00"}],
])
def test_bad_interval_structures_are_rejected(intervals):
    with pytest.raises(ValidationError):
        validate_opening_hours({"weekly": {}, "exceptions": {"2024-01-01": intervals}})


@pytest.mark.parametrize("value", [
    [], None, {"weekly": {}}, {"weekly": {"mon": []}, "exceptions": {}},
    {"weekly": {}, "exceptions": {"2024-02-30": []}},
    {"weekly": {}, "exceptions": {"20240101": []}},
    {"weekly": {}, "exceptions": {"9999-12-31": []}},
    {"weekly": {}, "exceptions": []}, {"weekly": {}, "exceptions": {}, "secret": 1},
])
def test_bad_schedule_structures_are_rejected(value):
    with pytest.raises(ValidationError):
        validate_opening_hours(value)


def test_closed_days_adjacent_intervals_midnight_and_holidays_are_valid():
    validate_opening_hours({})
    validate_opening_hours({"weekly": {day: [] for day in WEEKDAYS}, "exceptions": {"2024-01-01": []}})
    validate_opening_hours({"weekly": {}, "exceptions": {"2024-02-29": [
        {"start": "00:00", "end": "12:00"}, {"start": "12:00", "end": "24:00"},
    ]}})


def test_schedule_size_limits_are_enforced():
    from datetime import date, timedelta
    intervals = [{"start": f"{hour:02}:00", "end": f"{hour + 1:02}:00"} for hour in range(24)]
    validate_opening_hours({"weekly": {}, "exceptions": {"2024-01-01": intervals}})
    with pytest.raises(ValidationError, match="at most 24"):
        validate_opening_hours({"weekly": {}, "exceptions": {"2024-01-01": intervals + intervals[:1]}})
    exceptions = {(date(2024, 1, 1) + timedelta(days=offset)).isoformat(): [] for offset in range(366)}
    validate_opening_hours({"weekly": {}, "exceptions": exceptions})
    exceptions["2025-01-01"] = []
    with pytest.raises(ValidationError, match="at most 366"):
        validate_opening_hours({"weekly": {}, "exceptions": exceptions})
