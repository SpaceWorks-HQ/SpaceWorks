from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication


class EventStationCookieAuthentication(BaseAuthentication):
    """Schema marker; station views validate the path-bound cookie explicitly."""

    def authenticate(self, request):
        return None


class EventStationCookieAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = EventStationCookieAuthentication
    name = "EventStationCookie"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sw_event_station",
            "description": "Signed, event/version-bound venue-station session cookie.",
        }
