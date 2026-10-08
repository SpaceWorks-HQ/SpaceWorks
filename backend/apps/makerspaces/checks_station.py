"""System checks for kiosk Station session and operator-lease timing."""

from django.conf import settings
from django.core.checks import Error, register


_POSITIVE = (
    ("KIOSK_STATION_SESSION_TTL_SECONDS", "makerspaces.E101"),
    ("KIOSK_OPERATOR_LEASE_TTL_SECONDS", "makerspaces.E102"),
    ("KIOSK_OPERATOR_LEASE_RETENTION_SECONDS", "makerspaces.E103"),
)


@register()
def check_kiosk_station_timing(app_configs, **kwargs):
    errors = []
    for name, check_id in _POSITIVE:
        value = getattr(settings, name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(Error(f"{name} must be a positive integer.", id=check_id))
    if errors:
        return errors
    # A lease is clamped to its session anyway; a configured lease longer than the
    # session would only advertise a lifetime the server can never honour.
    if settings.KIOSK_OPERATOR_LEASE_TTL_SECONDS > settings.KIOSK_STATION_SESSION_TTL_SECONDS:
        errors.append(
            Error(
                "KIOSK_OPERATOR_LEASE_TTL_SECONDS must not exceed "
                "KIOSK_STATION_SESSION_TTL_SECONDS.",
                id="makerspaces.E104",
            )
        )
    return errors
