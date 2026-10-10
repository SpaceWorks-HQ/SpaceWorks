"""Published v1 vectors and canonical encodings (no database)."""

import pytest

from apps.devices import protocol
from apps.ed25519 import decode_key, fingerprint_public_key, sign_bytes, verify_bytes

SEED = bytes.fromhex(protocol.VECTOR_PRIVATE_SEED_HEX)
V = protocol.VECTORS


def test_request_vector_is_reproduced_byte_for_byte():
    r = V["request"]
    message = protocol.request_message(
        method="post", raw_target=r["raw_target"], timestamp=r["timestamp"],
        nonce=r["nonce"], body=r["body"],
    )
    assert protocol.sha256_hex(message) == r["message_sha256"]
    assert protocol.b64_encode(sign_bytes(message, SEED)) == r["signature"]
    verify_bytes(message, decode_key(r["signature"], label="sig", length=64),
                 decode_key(V["public_key"], label="key", length=32))


def test_enrollment_vector_is_reproduced_byte_for_byte():
    e = V["enrollment"]
    assert fingerprint_public_key(V["public_key"]) == V["fingerprint"]
    assert protocol.b64url_encode(e["challenge"]) == e["challenge_b64url"]
    message = protocol.enrollment_message(
        enrollment_id=e["enrollment_id"], makerspace_id=e["makerspace_id"],
        device_id=e["device_id"], purpose=e["purpose"], fingerprint=V["fingerprint"],
        challenge=e["challenge"],
    )
    assert protocol.sha256_hex(message) == e["message_sha256"]
    assert protocol.b64_encode(sign_bytes(message, SEED)) == e["signature"]


def test_query_order_and_body_are_signed():
    r = V["request"]
    base = dict(method="POST", timestamp=r["timestamp"], nonce=r["nonce"], body=r["body"])
    reordered = protocol.request_message(raw_target="/api/v1/device/heartbeat?a=1&b=2", **base)
    original = protocol.request_message(raw_target=r["raw_target"], **base)
    tampered = protocol.request_message(raw_target=r["raw_target"], **{**base, "body": b"{}"})
    assert len({reordered, original, tampered}) == 3


def test_domains_separate_the_two_messages():
    assert protocol.REQUEST_DOMAIN != protocol.ENROLLMENT_DOMAIN
    assert protocol.frame(b"ab", b"c") != protocol.frame(b"a", b"bc")


@pytest.mark.parametrize("nonce", ["short", "AAECAwQFBgcICQoLDA0ODw==", "AAECAwQFBgcICQoLDA0ODx", "a+b/" * 6])
def test_malformed_or_non_canonical_nonces_are_refused(nonce):
    with pytest.raises(protocol.ProtocolError):
        protocol.canonical_nonce(nonce)


@pytest.mark.parametrize("value", ["", "not base64!", V["public_key"].rstrip("="), V["public_key"] + "A"])
def test_public_keys_must_be_canonical_32_byte_base64(value):
    with pytest.raises(protocol.ProtocolError):
        protocol.b64_decode(value, label="public key", length=32)
