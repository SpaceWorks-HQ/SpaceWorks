import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import APIException, PermissionDenied

from apps.apiclients.crypto import decrypt_secret, encrypt_secret


class StationSecretUnavailable(APIException):
    status_code = 503
    default_detail = "Station credential encryption is not configured."
    default_code = "station_secret_unavailable"


def numeric_pin():
    return f"{secrets.randbelow(100_000_000):08d}"


def pin_digest(material):
    return make_password(material)


def pin_matches(material, digest):
    return check_password(material, digest)


def encrypt_pin(pin):
    try:
        return encrypt_secret(pin)
    except (ImproperlyConfigured, ValueError, TypeError) as exc:
        raise StationSecretUnavailable() from exc


def decrypt_pin(ciphertext):
    try:
        return decrypt_secret(ciphertext)
    except (ImproperlyConfigured, ValueError, TypeError) as exc:
        raise StationSecretUnavailable() from exc


def peppered_material(*, pepper, namespace, identity, version, pin):
    encoded_pepper = str(pepper or "").encode("utf-8")
    if len(encoded_pepper) < 32:
        raise StationSecretUnavailable()
    message = f"{namespace}:{identity}:{version}:{pin}".encode()
    return hmac.new(encoded_pepper, message, hashlib.sha256).hexdigest()


def assert_exact_origin(request, *, allowed_origins, refusal):
    if "X-Station-CSRF" not in request.headers:
        raise PermissionDenied(refusal)
    raw = request.headers.get("Origin") or request.headers.get("Referer", "")
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        raise PermissionDenied(refusal)
    candidate = f"{parts.scheme}://{parts.netloc}"
    resolved = allowed_origins() if callable(allowed_origins) else allowed_origins
    if candidate not in resolved:
        raise PermissionDenied(refusal)
