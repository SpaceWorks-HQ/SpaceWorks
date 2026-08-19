import hashlib
import re

from django.conf import settings
from django.core.cache import cache


NONCE_MAX_LENGTH = 128
NONCE_PATTERN = re.compile(r"\A[A-Za-z0-9._~-]+\Z")


def nonce_is_valid(nonce):
    return len(nonce) <= NONCE_MAX_LENGTH and bool(NONCE_PATTERN.fullmatch(nonce))


def body_could_re_encode_nonce(body):
    """Detect the ambiguous legacy encoding ``NONCE + newline + body``.

    Protocol v1 omits the nonce message part when the header is absent. A captured
    nonced request could otherwise be replayed as a nonce-less request by moving the
    nonce into the first body line while retaining the same signed bytes.
    """
    head, separator, _rest = body[: NONCE_MAX_LENGTH + 1].partition(b"\n")
    if not separator or not head:
        return False
    try:
        candidate = head.decode("ascii")
    except UnicodeDecodeError:
        return False
    return bool(NONCE_PATTERN.fullmatch(candidate))


def claim_nonce(client_id, nonce):
    # Keep keys fixed-size while preserving the existing per-client namespace.
    pair = f"{client_id}\0{nonce}".encode()
    key = f"apiclient-hmac-nonce:{hashlib.sha256(pair).hexdigest()}"
    # Future timestamps can remain acceptable for two complete skew windows.
    timeout = max(1, settings.HMAC_MAX_CLOCK_SKEW_SECONDS * 2 + 1)
    return cache.add(key, True, timeout=timeout)
