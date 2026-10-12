from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication


class KioskStationCookieAuthentication(BaseAuthentication):
    """Schema marker; kiosk views validate the path-bound cookie explicitly."""

    def authenticate(self, request):
        return None


class KioskStationCookieAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = KioskStationCookieAuthentication
    name = "KioskStationCookie"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sw_kiosk_station",
            "description": (
                "Signed, Station/version/session-bound kiosk cookie. Session-bound bearer "
                "material, not device-bound."
            ),
        }
