from urllib.parse import urlsplit

from django.core.exceptions import ValidationError


GOOGLE_MAPS_HOSTS = {
    "google.com",
    "www.google.com",
    "maps.google.com",
    "maps.app.goo.gl",
    "goo.gl",
    "g.co",
}
GOOGLE_MAPS_ERROR = "Enter a valid Google Maps link."
DEFAULT_PRESENCE_PRESETS = [60, 120, 240]


def validate_presence_presets(value):
    if not isinstance(value, list):
        raise ValidationError("Provide one or more presence session lengths.")
    # The model stores [] for an unconfigured policy. presence_presets() resolves
    # it to DEFAULT_PRESENCE_PRESETS; exports and ordinary editors use that sentinel.
    if not value:
        return value
    if any(type(minutes) is not int or not 15 <= minutes <= 480 for minutes in value):
        raise ValidationError("Presence session lengths must be whole minutes from 15 to 480.")
    if len(set(value)) != len(value):
        raise ValidationError("Presence session lengths must be unique.")
    return value


def validate_google_maps_url(value):
    if not (value or "").strip():
        return

    parsed = urlsplit(value)
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or host not in GOOGLE_MAPS_HOSTS
    ):
        raise ValidationError(GOOGLE_MAPS_ERROR)

    path = parsed.path or ""
    if host in {"google.com", "www.google.com"} and not path.startswith("/maps"):
        raise ValidationError(GOOGLE_MAPS_ERROR)
    if host == "goo.gl" and not path.startswith("/maps"):
        raise ValidationError(GOOGLE_MAPS_ERROR)
    if host == "g.co" and not path.startswith("/kgs"):
        raise ValidationError(GOOGLE_MAPS_ERROR)
