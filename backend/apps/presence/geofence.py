"""Server-authoritative, privacy-preserving presence geofence checks."""

from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt


ACCURACY_CEILING_M = 50
EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class GeofenceResult:
    in_range: bool | None
    reason: str | None
    distance_m: float | None
    accuracy_m: float | None


def haversine_distance_m(latitude_a, longitude_a, latitude_b, longitude_b):
    latitude_delta = radians(latitude_b - latitude_a)
    longitude_delta = radians(longitude_b - longitude_a)
    component = sin(latitude_delta / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(longitude_delta / 2) ** 2
    return EARTH_RADIUS_M * 2 * asin(sqrt(component))


def evaluate_geofence(makerspace, *, latitude, longitude, accuracy):
    # Additive master switch (plan A6) in front of the existing configuration check, not
    # a replacement. `None` means "not checked", which is exactly the dormant behaviour
    # an unconfigured space already has -- and the geofence stays ADVISORY either way:
    # this can only remove a classification, never start blocking a check-in.
    from apps.makerspaces.platform import feature_enabled

    if not feature_enabled(makerspace, "presence.geofence"):
        return None
    if not makerspace.geofence_effective:
        return None
    if latitude is None or longitude is None or accuracy is None:
        return GeofenceResult(in_range=None, reason="missing_coordinates", distance_m=None, accuracy_m=None)
    if not all(isfinite(value) for value in (latitude, longitude, accuracy)):
        return GeofenceResult(in_range=None, reason="missing_coordinates", distance_m=None, accuracy_m=None)
    distance_m = haversine_distance_m(float(makerspace.geofence_latitude), float(makerspace.geofence_longitude), latitude, longitude)
    if accuracy > ACCURACY_CEILING_M:
        return GeofenceResult(in_range=False, reason="low_accuracy", distance_m=distance_m, accuracy_m=accuracy)
    in_range = distance_m - min(accuracy, ACCURACY_CEILING_M) <= makerspace.geofence_radius_m
    return GeofenceResult(
        in_range=in_range,
        reason=None if in_range else "out_of_range",
        distance_m=distance_m,
        accuracy_m=accuracy,
    )


def geofence_metadata(result):
    if result is None:
        return {}
    metadata = {"geofence_checked": True, "in_range": result.in_range}
    if result.reason is not None:
        metadata["reason"] = result.reason
    if result.distance_m is not None:
        metadata["distance_bucket"] = _bucket(result.distance_m)
    if result.accuracy_m is not None:
        metadata["accuracy_bucket"] = _bucket(result.accuracy_m)
    return metadata


def _bucket(value):
    if value <= 10:
        return "0-10m"
    if value <= 25:
        return "11-25m"
    if value <= 50:
        return "26-50m"
    return "50m+"