"""Format-neutral Ed25519 primitives shared by signed protocol modules."""

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class Ed25519Error(ValueError):
    pass


def generate_keypair():
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private_raw, public_raw


def encode_key(raw):
    if not isinstance(raw, bytes):
        raise Ed25519Error("Ed25519 material must be bytes.")
    return base64.b64encode(raw).decode("ascii")


def decode_key(value, *, label, length):
    if not isinstance(value, str):
        raise Ed25519Error(f"The {label} encoding is invalid.")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise Ed25519Error(f"The {label} encoding is invalid.") from exc
    if len(raw) != length:
        raise Ed25519Error(f"An Ed25519 {label} must be {length} bytes.")
    return raw


def fingerprint_public_key(public_key):
    raw = (
        decode_key(public_key, label="public key", length=32)
        if isinstance(public_key, str)
        else public_key
    )
    if not isinstance(raw, bytes) or len(raw) != 32:
        raise Ed25519Error("An Ed25519 public key must be 32 bytes.")
    return hashlib.sha256(raw).hexdigest()


def sign_bytes(payload, private_key):
    if not isinstance(payload, bytes):
        raise Ed25519Error("The signed payload must be bytes.")
    if not isinstance(private_key, bytes) or len(private_key) != 32:
        raise Ed25519Error("An Ed25519 private key must be 32 bytes.")
    return Ed25519PrivateKey.from_private_bytes(private_key).sign(payload)


def verify_bytes(payload, signature, public_key):
    if not isinstance(payload, bytes):
        raise Ed25519Error("The signed payload must be bytes.")
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise Ed25519Error("An Ed25519 signature must be 64 bytes.")
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise Ed25519Error("An Ed25519 public key must be 32 bytes.")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except (InvalidSignature, ValueError) as exc:
        raise Ed25519Error("The Ed25519 signature is invalid.") from exc
