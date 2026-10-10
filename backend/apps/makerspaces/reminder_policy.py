"""Bounded, explicit lead-hour policy for attendance reminders."""

from django.core.exceptions import ValidationError


def default_reminder_lead_hours():
    return [24]


def validate_reminder_lead_hours(value):
    if (not isinstance(value, list) or len(value) > 100
            or any(type(hour) is not int or not 1 <= hour <= 8760 for hour in value)
            or len(set(value)) != len(value)):
        raise ValidationError("Use up to 100 unique whole lead hours from 1 to 8760; [] disables reminders.")
    return value


def reminder_offsets(makerspace, domain):
    hours = getattr(makerspace, f"{domain}_reminder_lead_hours")
    validate_reminder_lead_hours(hours)
    return tuple(-hour * 3600 for hour in hours)
