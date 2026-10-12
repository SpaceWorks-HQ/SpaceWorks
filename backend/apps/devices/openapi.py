"""drf-spectacular security scheme for signed device requests."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class DeviceSignatureScheme(OpenApiAuthenticationExtension):
    target_class = "apps.devices.authentication.DeviceAuthentication"
    name = "DeviceSignature"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-Device-Signature",
            "description": (
                "Ed25519 signature (protocol v1) over the length-framed request message; "
                "requires X-Device-Id, X-Device-Key-Version, X-Device-Signature-Version, "
                "X-Device-Timestamp and X-Device-Nonce. See docs/device-protocol.md."
            ),
        }
