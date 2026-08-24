"""Short Ed25519 launch grants returned only after host nonce consumption."""

from __future__ import annotations

import base64
from datetime import timedelta
from pathlib import Path
import stat

from apps.ed25519 import (
    Ed25519Error,
    decode_key,
    fingerprint_public_key,
    encode_key,
    generate_keypair,
    sign_bytes,
    verify_bytes,
)

from .host_capability_types import (
    CAPABILITY_VERSION,
    CapabilityError,
    canonical_json,
    timestamp,
    timestamp_text,
    utc_now,
)


SIGNATURE_DOMAIN = b"spaceworks-host-launch-grant-v1\x00"


def generate_launch_grant_keys(private_key_path, public_key_path):
    private, public = generate_keypair()
    _write_key(private_key_path, encode_key(private), 0o600)
    _write_key(public_key_path, encode_key(public), 0o444)
    return fingerprint_public_key(public)


def _write_key(path, value, mode):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        import os
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            mode,
        )
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _trusted_key(path, *, private, require_root_owned=True):
    path = Path(path)
    try:
        file_stat = path.stat(follow_symlinks=False)
        parent_stat = path.parent.stat()
        raw = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise CapabilityError("Launch-grant key is unavailable.") from exc
    if require_root_owned and (
        file_stat.st_uid != 0
        or parent_stat.st_uid != 0
        or parent_stat.st_mode & 0o022
        or file_stat.st_mode & (0o077 if private else 0o022)
        or not stat.S_ISREG(file_stat.st_mode)
    ):
        raise CapabilityError("Launch-grant key is misowned or writable.")
    try:
        return decode_key(
            raw,
            label="private key" if private else "public key",
            length=32,
        )
    except Ed25519Error as exc:
        raise CapabilityError("Launch-grant key is invalid.") from exc


def sign_launch_grant(
    record,
    request,
    *,
    private_key_path,
    public_key_path,
    lifetime_seconds=15,
    require_root_owned=True,
):
    now = utc_now()
    expiry = min(timestamp(record.expires_at), now + timedelta(seconds=lifetime_seconds))
    grant = {
        "version": CAPABILITY_VERSION,
        "nonce": record.nonce,
        "issued_at": timestamp_text(now),
        "expires_at": timestamp_text(expiry),
        "request": request.payload(),
        "marker_binding": record.marker_binding,
    }
    private = _trusted_key(
        private_key_path, private=True, require_root_owned=require_root_owned
    )
    public = _trusted_key(
        public_key_path, private=False, require_root_owned=require_root_owned
    )
    signature = sign_bytes(SIGNATURE_DOMAIN + canonical_json(grant), private)
    return {
        "grant": grant,
        "signature": {
            "algorithm": "ed25519",
            "signer_fingerprint": fingerprint_public_key(public),
            "value": base64.b64encode(signature).decode("ascii"),
        },
    }


def verify_launch_grant(
    document,
    request,
    *,
    public_key_path,
    require_root_owned=True,
    now=None,
):
    if not isinstance(document, dict) or set(document) != {"grant", "signature"}:
        raise CapabilityError("Launch grant has an invalid shape.")
    grant, signature = document["grant"], document["signature"]
    required = {"version", "nonce", "issued_at", "expires_at", "request", "marker_binding"}
    if not isinstance(grant, dict) or set(grant) != required:
        raise CapabilityError("Launch grant payload has an invalid shape.")
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm", "signer_fingerprint", "value"
    } or signature["algorithm"] != "ed25519":
        raise CapabilityError("Launch grant signature has an invalid shape.")
    if grant["version"] != CAPABILITY_VERSION or grant["request"] != request.payload():
        raise CapabilityError("Launch grant does not bind the consume request.")
    current = now or utc_now()
    issued_at = timestamp(grant["issued_at"])
    expires_at = timestamp(grant["expires_at"])
    if issued_at > current or expires_at <= current or expires_at <= issued_at:
        raise CapabilityError("Launch grant is expired or not yet valid.")
    public = _trusted_key(
        public_key_path, private=False, require_root_owned=require_root_owned
    )
    if signature["signer_fingerprint"] != fingerprint_public_key(public):
        raise CapabilityError("Launch grant signer does not match the mounted key.")
    try:
        raw_signature = base64.b64decode(signature["value"], validate=True)
        verify_bytes(
            SIGNATURE_DOMAIN + canonical_json(grant), raw_signature, public
        )
    except (ValueError, Ed25519Error) as exc:
        raise CapabilityError("Launch grant signature is invalid.") from exc
    return grant
