"""Fail-closed host capability gate for Lane E compound archive production."""

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import stat

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings

from apps.backup.compound_protocol import (
    PROTOCOL_FAMILY,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_MAXIMUM,
    SUPPORTED_PROTOCOL_MINIMUM,
)
from apps.backup.host_marker import MarkerError, _assert_trusted_file
from apps.backup.host_marker_file import write_json_fsynced
from apps.backup.recipient_selection import BackupBuildError
from apps.ed25519 import Ed25519Error, decode_key, fingerprint_public_key


MARKER_VERSION = 1
PRIVILEGED_SCRIPT_NAMES = (
    "host-capability.py",
    "import-backup.sh",
    "restore.sh",
    "spaceworks-compose.sh",
    "validate-compose-wrapper.py",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MIGRATION_VERSION = re.compile(r"django-migrations-v1:[0-9a-f]{64}")
_MAX_PROTOCOL_VERSION = 65_535


class ProducerCapabilityRefused(BackupBuildError):
    def __init__(self, reason, detail):
        self.reason = reason
        super().__init__(f"Compound archive refused [{reason}]: {detail}")


@dataclass(frozen=True)
class ProducerCapability:
    script_sha256: dict[str, str]
    entrypoint_sha256: str
    protocol_minimum: str
    protocol_maximum: str
    signing_key_fingerprint: str
    migration_version: str


def _refuse(reason, detail, *, cause=None):
    error = ProducerCapabilityRefused(f"producer-capability-{reason}", detail)
    if cause is None:
        raise error
    raise error from cause


def _protocol_number(value):
    if not isinstance(value, str) or not value.startswith(PROTOCOL_FAMILY):
        raise ValueError("protocol family")
    suffix = value.removeprefix(PROTOCOL_FAMILY)
    if not suffix.isascii() or not suffix.isdecimal() or suffix.startswith("0"):
        raise ValueError("protocol version")
    number = int(suffix)
    if not 1 <= number <= _MAX_PROTOCOL_VERSION:
        raise ValueError("protocol range")
    return number


def parse_capability_marker(payload):
    required = {
        "version", "privileged_scripts", "entrypoint_sha256",
        "compound_protocol", "signing_key_fingerprint", "migration_version",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("capability marker has an invalid top-level shape")
    if type(payload["version"]) is not int or payload["version"] != MARKER_VERSION:
        raise ValueError("capability marker version is unsupported")
    scripts = payload["privileged_scripts"]
    if not isinstance(scripts, dict) or set(scripts) != set(PRIVILEGED_SCRIPT_NAMES):
        raise ValueError("capability marker privileged-script set is invalid")
    if any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in scripts.values()):
        raise ValueError("capability marker privileged-script digest is invalid")
    entrypoint = payload["entrypoint_sha256"]
    fingerprint = payload["signing_key_fingerprint"]
    migration = payload["migration_version"]
    if not isinstance(entrypoint, str) or not _SHA256.fullmatch(entrypoint):
        raise ValueError("capability marker entrypoint digest is invalid")
    if not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint):
        raise ValueError("capability marker signing-key fingerprint is invalid")
    if not isinstance(migration, str) or not _MIGRATION_VERSION.fullmatch(migration):
        raise ValueError("capability marker migration version is invalid")
    protocol = payload["compound_protocol"]
    if not isinstance(protocol, dict) or set(protocol) != {"minimum", "maximum"}:
        raise ValueError("capability marker protocol range has an invalid shape")
    minimum = _protocol_number(protocol["minimum"])
    maximum = _protocol_number(protocol["maximum"])
    if minimum > maximum:
        raise ValueError("capability marker protocol range is inverted")
    return ProducerCapability(
        script_sha256=dict(scripts),
        entrypoint_sha256=entrypoint,
        protocol_minimum=protocol["minimum"],
        protocol_maximum=protocol["maximum"],
        signing_key_fingerprint=fingerprint,
        migration_version=migration,
    )


def _sha256_installed_file(path):
    path = Path(path)
    file_stat = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(file_stat.st_mode) or stat.S_ISLNK(file_stat.st_mode):
        raise OSError("installed capability input is not a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_migration_version(migrations_root):
    root = Path(migrations_root)
    files = sorted(
        path for path in root.glob("*/migrations/[0-9][0-9][0-9][0-9]_*.py")
    )
    if not files:
        raise OSError("no installed migration files were found")
    digest = hashlib.sha256(b"spaceworks-django-migrations-v1\0")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(len(content).to_bytes(8, "big") + content)
    return f"django-migrations-v1:{digest.hexdigest()}"


def capability_marker_payload(
    *, script_paths, entrypoint_path, verification_public_key, migrations_root,
    protocol_minimum=SUPPORTED_PROTOCOL_MINIMUM,
    protocol_maximum=SUPPORTED_PROTOCOL_MAXIMUM,
):
    if set(script_paths) != set(PRIVILEGED_SCRIPT_NAMES):
        raise ValueError("The installed privileged-script set is incomplete.")
    public = decode_key(verification_public_key, label="public key", length=32)
    payload = {
        "version": MARKER_VERSION,
        "privileged_scripts": {
            name: _sha256_installed_file(script_paths[name])
            for name in PRIVILEGED_SCRIPT_NAMES
        },
        "entrypoint_sha256": _sha256_installed_file(entrypoint_path),
        "compound_protocol": {
            "minimum": protocol_minimum,
            "maximum": protocol_maximum,
        },
        "signing_key_fingerprint": fingerprint_public_key(public),
        "migration_version": installed_migration_version(migrations_root),
    }
    parse_capability_marker(payload)
    return payload


def write_capability_marker_fsynced(path, payload, *, require_root_owned=True):
    parse_capability_marker(payload)
    write_json_fsynced(path, payload, require_root_owned=require_root_owned)


def read_capability_marker(path):
    path = Path(path)
    try:
        path.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        _refuse("marker-absent", "the host-installed marker is absent.", cause=exc)
    except OSError as exc:
        _refuse("marker-unreadable", "the host-installed marker is unreadable.", cause=exc)
    try:
        _assert_trusted_file(path)
    except MarkerError as exc:
        detail = str(exc)
        if "root-owned" in detail:
            _refuse("marker-ownership", "the marker or its directory is not root-owned.", cause=exc)
        if "writable" in detail:
            _refuse("marker-mode", "the marker or its directory has an unsafe mode.", cause=exc)
        _refuse("marker-unreadable", "the host-installed marker is not a trusted file.", cause=exc)
    try:
        if stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) != 0o444:
            _refuse("marker-mode", "the marker mode is not 0444.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return parse_capability_marker(payload)
    except ProducerCapabilityRefused:
        raise
    except OSError as exc:
        _refuse("marker-unreadable", "the host-installed marker is unreadable.", cause=exc)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _refuse("marker-malformed", "the host-installed marker is malformed.", cause=exc)


def _signing_fingerprint():
    try:
        private = decode_key(
            settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY,
            label="private key", length=32,
        )
        public = decode_key(
            settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY,
            label="public key", length=32,
        )
        derived = Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    except (Ed25519Error, ValueError) as exc:
        _refuse("signing-fingerprint", "the producer signing identity is invalid.", cause=exc)
    if not hmac.compare_digest(derived, public):
        _refuse("signing-fingerprint", "the producer private and verification keys do not match.")
    return fingerprint_public_key(public)


def assert_producer_capability():
    marker = read_capability_marker(settings.BACKUP_PRODUCER_CAPABILITY_MARKER_PATH)
    scripts_dir = Path(settings.BACKUP_PRODUCER_PRIVILEGED_SCRIPTS_DIR)
    for name in PRIVILEGED_SCRIPT_NAMES:
        try:
            actual = _sha256_installed_file(scripts_dir / name)
        except OSError as exc:
            _refuse("privileged-script-hash", f"installed privileged script {name} is unreadable.", cause=exc)
        if not hmac.compare_digest(actual, marker.script_sha256[name]):
            _refuse("privileged-script-hash", f"installed privileged script {name} changed.")
    try:
        entrypoint = _sha256_installed_file(settings.BACKUP_PRODUCER_ENTRYPOINT_PATH)
    except OSError as exc:
        _refuse("entrypoint-hash", "the installed common entrypoint is unreadable.", cause=exc)
    if not hmac.compare_digest(entrypoint, marker.entrypoint_sha256):
        _refuse("entrypoint-hash", "the installed common entrypoint changed.")
    version = _protocol_number(PROTOCOL_VERSION)
    if not _protocol_number(marker.protocol_minimum) <= version <= _protocol_number(marker.protocol_maximum):
        _refuse("protocol-range", "the emitted compound protocol is outside the host-supported range.")
    if not hmac.compare_digest(_signing_fingerprint(), marker.signing_key_fingerprint):
        _refuse("signing-fingerprint", "the producer signer differs from the host-installed trust key.")
    try:
        migration_version = installed_migration_version(settings.BACKUP_PRODUCER_MIGRATIONS_DIR)
    except OSError as exc:
        _refuse("migration-version", "the installed migration version is unreadable.", cause=exc)
    if not hmac.compare_digest(migration_version, marker.migration_version):
        _refuse("migration-version", "the producer migration version differs from the host expectation.")
    return marker
