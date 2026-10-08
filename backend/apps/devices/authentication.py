"""DRF authentication for signed device requests (protocol v1).

Order matters and is pinned by the source-gate AST guard: parse and hash, resolve the
Device through the canonical servable-makerspace queryset, select that ONE tenant,
call the late source gate, and only then run the locked nonce claim. A gate refusal
therefore consumes no nonce, and a device can never select a tenant other than its own.
"""

import re
import time
import uuid
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.devices import protocol
from apps.devices.models import Device
from apps.devices.services_requests import claim_signed_request
from apps.makerspaces.servability import servable_queryset

AUTH_SCHEME = "SpaceWorks-Device-v1"
_DIGITS = re.compile(r"^[1-9][0-9]{0,9}$")


class DeviceAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return AUTH_SCHEME

    def authenticate(self, request):
        headers = request.headers
        raw_device_id = headers.get("X-Device-Id")
        if raw_device_id is None:
            return None
        device_id = _uuid(raw_device_id)
        key_version = _positive(headers.get("X-Device-Key-Version"), "key version")
        if headers.get("X-Device-Signature-Version") != protocol.VERSION:
            raise AuthenticationFailed("Unsupported device signature version.")
        timestamp = _positive(headers.get("X-Device-Timestamp"), "timestamp")
        if abs(int(time.time()) - timestamp) > settings.DEVICE_SIGNATURE_MAX_SKEW_SECONDS:
            raise AuthenticationFailed("Device request timestamp is outside the allowed skew.")
        try:
            nonce = protocol.canonical_nonce(headers.get("X-Device-Nonce"))
            signature = protocol.b64_decode(
                headers.get("X-Device-Signature"), label="signature", length=64
            )
        except protocol.ProtocolError as exc:
            raise AuthenticationFailed(str(exc)) from exc
        message = protocol.request_message(
            method=request.method, raw_target=raw_request_target(request._request),
            timestamp=timestamp, nonce=nonce, body=request._request.body,
        )
        device = servable_queryset(
            Device.objects.filter(pk=device_id), relation="makerspace"
        ).only("id", "makerspace_id").first()
        if device is None:
            raise AuthenticationFailed("Device authorization is not active.")
        request.selected_makerspace_id = device.makerspace_id
        _assert_source_gate(request)
        principal = claim_signed_request(
            device_id=device.pk, makerspace_id=device.makerspace_id,
            key_version=key_version, nonce=nonce, message=message,
            signature=signature, now=timezone.now(),
        )
        return principal, None


def _assert_source_gate(request):
    from apps.tenant_migration.gate_runtime import assert_request_write_allowed

    assert_request_write_allowed(request)


def raw_request_target(django_request):
    """The exact request-target bytes the server received; never a normalized fallback."""
    meta = django_request.META
    raw = meta.get("RAW_URI") or meta.get("REQUEST_URI")
    scope = getattr(django_request, "scope", None)
    if not raw and scope:
        raw = scope.get("raw_path", b"").decode("latin-1")
        query = scope.get("query_string", b"").decode("latin-1")
        raw = f"{raw}?{query}" if raw and query else raw
    if not raw or not raw.startswith("/"):
        raise AuthenticationFailed("The raw request target is unavailable.")
    if unquote(urlsplit(raw).path) != django_request.path:
        raise AuthenticationFailed("The raw request target does not match the route.")
    return raw


def _uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise AuthenticationFailed("Invalid device id.") from exc
    if str(parsed) != value:
        raise AuthenticationFailed("Invalid device id.")
    return parsed


def _positive(value, label):
    if not isinstance(value, str) or not _DIGITS.match(value):
        raise AuthenticationFailed(f"Invalid device {label}.")
    return int(value)
