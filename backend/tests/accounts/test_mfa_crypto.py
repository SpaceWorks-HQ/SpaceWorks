"""Cryptographic vectors and the exact accepted clock window (no database)."""

import base64

import pytest

from apps.accounts.mfa_crypto import matching_step, provisioning_uri, totp

SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.mark.parametrize("timestamp,expected", [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
    (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130"),
])
def test_rfc6238_sha1_vectors_truncated_to_six_digits(timestamp, expected):
    assert totp(SECRET, timestamp // 30) == expected


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_accepts_one_adjacent_step(offset):
    assert matching_step(SECRET, totp(SECRET, 100 + offset), 3000) == 100 + offset


@pytest.mark.parametrize("offset", [-2, 2])
def test_refuses_outside_one_step(offset):
    assert matching_step(SECRET, totp(SECRET, 100 + offset), 3000) is None


def test_refuses_replay_and_older_steps_after_future_window_was_used():
    for step in (99, 100, 101):
        assert matching_step(SECRET, totp(SECRET, step), 3000, last_step=101) is None


@pytest.mark.parametrize("code", ["", "12345", "1234567", "１２３４５６", "abcdef", None])
def test_rejects_malformed_codes(code):
    assert matching_step(SECRET, code, 3000) is None


def test_uri_encodes_identity_and_explicit_algorithm():
    uri = provisioning_uri(SECRET, "person@example.test")
    assert "SpaceWorks%3Aperson%40example.test" in uri
    assert f"secret={SECRET}" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri
