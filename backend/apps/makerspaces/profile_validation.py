"""Portable location and wall-clock schedule validation; no database access."""

import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError


# ISO 3166-1 alpha-2, including dependent territories. No pseudo-country codes.
COUNTRY_CODES = tuple(sorted("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN
BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL
GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM
JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME
MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP
NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD
SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO
TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split()))
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def default_timezone():
    return settings.TIME_ZONE


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError("Enter a valid IANA timezone.", code="invalid_timezone")


def validate_country(value):
    if value and value not in COUNTRY_CODES:
        raise ValidationError("Enter an ISO 3166-1 alpha-2 country code.", code="invalid_country")


def _minute(value, *, end=False):
    if end and value == "24:00":
        return 1440
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValidationError("Use HH:MM (24:00 is allowed only as an end).")
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


def _intervals(value):
    if not isinstance(value, list) or len(value) > 24:
        raise ValidationError("Each day needs a list of at most 24 intervals.")
    previous_end = -1
    for interval in value:
        if not isinstance(interval, dict) or set(interval) != {"start", "end"}:
            raise ValidationError("Each interval needs exactly start and end.")
        start = _minute(interval["start"])
        end = _minute(interval["end"], end=True)
        if start >= end or start < previous_end:
            raise ValidationError("Intervals must be sorted, non-overlapping and end after start. Split overnight hours across days.")
        previous_end = end


def validate_opening_hours(value):
    """{} means always open; [] closes a configured day. Exceptions replace a day."""
    if value == {}:
        return
    if not isinstance(value, dict) or set(value) != {"weekly", "exceptions"}:
        raise ValidationError("Use weekly and exceptions, or {} for always open.")
    weekly, exceptions = value["weekly"], value["exceptions"]
    if not isinstance(weekly, dict) or (weekly and set(weekly) != set(WEEKDAYS)):
        raise ValidationError("Weekly hours must contain all seven weekdays, or be empty for always open.")
    for intervals in weekly.values():
        _intervals(intervals)
    if not isinstance(exceptions, dict) or len(exceptions) > 366:
        raise ValidationError("Exceptions must map at most 366 dates to intervals.")
    for day, intervals in exceptions.items():
        try:
            parsed = date.fromisoformat(day)
            if parsed.isoformat() != day:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError("Exception dates must use YYYY-MM-DD.")
        if parsed == date.max:
            raise ValidationError("Exception dates must have a representable following day.")
        _intervals(intervals)
