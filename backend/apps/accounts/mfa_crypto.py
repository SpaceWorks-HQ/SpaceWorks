"""RFC 6238 SHA-1 TOTP; constant-time comparisons and hashed recovery tokens."""

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

from django.contrib.auth.hashers import make_password


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return f"{number % 1000000:06d}"


def matching_step(secret, code, timestamp, last_step=-1):
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int(timestamp // 30)
    # Prefer current, then adjacent windows; never accept an already-consumed step.
    for step in (current, current - 1, current + 1):
        if step >= 0 and step > last_step and hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def recovery_codes():
    codes = [secrets.token_hex(10) for _ in range(10)]
    return codes, [make_password(code) for code in codes]


def provisioning_uri(secret, username):
    return "otpauth://totp/" + quote(f"SpaceWorks:{username}", safe="") + "?" + urlencode({
        "secret": secret, "issuer": "SpaceWorks", "algorithm": "SHA1", "digits": 6, "period": 30,
    })
