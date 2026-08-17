import pytest

from apps.encryption.crypto import (
    PiiAuthenticationFailed,
    PiiMalformedEnvelope,
    decrypt,
    encrypt,
    is_envelope,
    parse_envelope,
)


@pytest.fixture
def args():
    return {
        "key_version": 1,
        "makerspace_id": 9,
        "table": "hardware_requests_hardwarerequest",
        "pk": 12,
        "field": "requester_name",
    }


def test_aes_gcm_envelopes_round_trip_and_use_fresh_nonces(args):
    dek = b"d" * 32
    first = encrypt(b"Ada Lovelace", dek, **args)
    second = encrypt(b"Ada Lovelace", dek, **args)
    assert first != second
    assert is_envelope(first)
    assert decrypt(first, dek, **{k: v for k, v in args.items() if k != "key_version"}) == b"Ada Lovelace"


@pytest.mark.parametrize(
    "changed", [{"makerspace_id": 10}, {"table": "other"}, {"pk": 13}, {"field": "email"}]
)
def test_aes_gcm_binds_every_aad_component(args, changed):
    encrypted = encrypt(b"secret", b"d" * 32, **args)
    decrypt_args = {k: v for k, v in args.items() if k != "key_version"}
    decrypt_args.update(changed)
    with pytest.raises(PiiAuthenticationFailed):
        decrypt(encrypted, b"d" * 32, **decrypt_args)


def test_envelope_rejects_malformed_nonce_and_ciphertext(args):
    encrypted = encrypt(b"secret", b"d" * 32, **args)
    with pytest.raises(PiiMalformedEnvelope):
        decrypt("pii:gcm:v1:1:x:AA", b"d" * 32, **{k: v for k, v in args.items() if k != "key_version"})
    parts = encrypted.split(":")
    parts[-1] = ("A" if parts[-1][0] != "A" else "B") + parts[-1][1:]
    altered = ":".join(parts)
    with pytest.raises(PiiAuthenticationFailed):
        decrypt(altered, b"d" * 32, **{k: v for k, v in args.items() if k != "key_version"})


def test_envelope_rejects_noncanonical_base64url_padding_bits():
    with pytest.raises(PiiMalformedEnvelope):
        parse_envelope(
            "pii:gcm:v1:1:AAAAAAAAAAAAAAAA:AAAAAAAAAAAAAAAAAAAAAB"
        )
