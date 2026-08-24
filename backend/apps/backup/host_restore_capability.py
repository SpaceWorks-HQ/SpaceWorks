"""Host-installed compatibility gate for the Lane E compound coordinator."""

import hashlib
import json
from pathlib import Path
import stat

from apps.backup.outer_manifest import PROTOCOL_VERSION

from .compound_restore_types import CompoundRestoreRefused


CAPABILITY_VERSION = 1


class InstalledHostCapability:
    """Validate, never create, the operator-installed restore capability record."""

    def __init__(
        self, *, record_path, installed_files, installed_migration,
        require_root_owned=True,
    ):
        self.record_path = Path(record_path)
        self.installed_files = {
            name: Path(path) for name, path in installed_files.items()
        }
        self.installed_migration = installed_migration
        self.require_root_owned = require_root_owned

    def validate(self, *, inputs, manifest, topology):
        record = self._read_record()
        expected = {
            "version": CAPABILITY_VERSION,
            "compound_protocol": PROTOCOL_VERSION,
            "signing_key_fingerprint": manifest["archive_signature"][
                "signer_fingerprint"
            ],
            "migration_version": self.installed_migration,
            "topology_path": topology.path,
            "writer_set": list(topology.writer_set),
            "installed_files": {
                name: _sha256(path)
                for name, path in sorted(self.installed_files.items())
            },
        }
        if record != expected:
            raise CompoundRestoreRefused(
                "The host compound capability does not match the installed "
                "scripts, entrypoint, protocol, signer, migration, or topology."
            )
        return {
            "validated": True,
            "record_sha256": _digest(record),
            "compound_protocol": record["compound_protocol"],
            "migration_version": record["migration_version"],
        }

    def _read_record(self):
        try:
            record_stat = self.record_path.stat(follow_symlinks=False)
            parent_stat = self.record_path.parent.stat()
            raw = self.record_path.read_text(encoding="utf-8")
            record = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CompoundRestoreRefused(
                "The host compound capability record is missing or unreadable."
            ) from exc
        if self.require_root_owned and (
            not stat.S_ISREG(record_stat.st_mode)
            or record_stat.st_uid != 0
            or parent_stat.st_uid != 0
            or record_stat.st_mode & 0o077
            or parent_stat.st_mode & 0o022
        ):
            raise CompoundRestoreRefused(
                "The host compound capability record is not private and root-owned."
            )
        if not isinstance(record, dict):
            raise CompoundRestoreRefused(
                "The host compound capability record has an invalid shape."
            )
        return record


def _sha256(path):
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CompoundRestoreRefused(
            f"The installed host capability file {path.name} is unreadable."
        ) from exc
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
