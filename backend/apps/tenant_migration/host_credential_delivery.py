"""Durable one-time host-file delivery for D7-created credentials."""

from __future__ import annotations

import json
from pathlib import Path
import stat

from apps.backup.host_private_file import (
    unlink_private_file_fsynced,
    write_private_file_fsynced,
)
from .tenant_restore_types import TenantRestoreRefused


class CredentialDeliveryStore:
    def __init__(self, root, *, require_root_owned=True):
        self.root = Path(root)
        self.require_root_owned = require_root_owned

    def _paths(self, provenance):
        if not isinstance(provenance, str) or len(provenance) != 64 or any(
            character not in "0123456789abcdef" for character in provenance
        ):
            raise TenantRestoreRefused("Credential delivery provenance is invalid.")
        return (
            self.root / f"{provenance}.secret.json",
            self.root / f"{provenance}.ack.json",
        )

    def prepare(self, *, provenance, kind, target, secret):
        secret_path, ack_path = self._paths(provenance)
        if ack_path.exists():
            raise TenantRestoreRefused("Credential delivery was already acknowledged.")
        payload = {
            "version": 1,
            "provenance": provenance,
            "kind": kind,
            "target": str(target),
            "secret": secret,
        }
        if secret_path.exists():
            if self._read(secret_path) != payload:
                raise TenantRestoreRefused("Credential delivery retry conflicts.")
            return payload
        write_private_file_fsynced(
            secret_path,
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            require_root_owned=self.require_root_owned,
        )
        return payload

    def get_or_prepare(self, *, provenance, kind, target, secret_factory):
        secret_path, ack_path = self._paths(provenance)
        if ack_path.exists():
            raise TenantRestoreRefused("Credential delivery was already acknowledged.")
        if secret_path.exists():
            payload = self._read(secret_path)
            if (
                payload.get("provenance") != provenance
                or payload.get("kind") != kind
                or payload.get("target") != str(target)
                or not payload.get("secret")
            ):
                raise TenantRestoreRefused("Credential delivery retry conflicts.")
            return payload
        return self.prepare(
            provenance=provenance,
            kind=kind,
            target=target,
            secret=secret_factory(),
        )

    def read_unacknowledged(self, provenance):
        secret_path, ack_path = self._paths(provenance)
        if ack_path.exists():
            raise TenantRestoreRefused("Credential delivery was already acknowledged.")
        return self._read(secret_path)

    def acknowledge(self, provenance, *, host_principal):
        secret_path, ack_path = self._paths(provenance)
        if ack_path.exists():
            return self._read(ack_path)
        payload = {
            "version": 1,
            "provenance": provenance,
            "acknowledged_by": host_principal,
        }
        write_private_file_fsynced(
            ack_path,
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            mode=0o400,
            require_root_owned=self.require_root_owned,
        )
        if secret_path.exists():
            unlink_private_file_fsynced(secret_path)
        return payload

    def _read(self, path):
        try:
            file_stat = path.stat(follow_symlinks=False)
            parent_stat = path.parent.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_mode & 0o077
                or not stat.S_ISDIR(parent_stat.st_mode)
                or (
                    self.require_root_owned
                    and (
                        file_stat.st_uid != 0
                        or parent_stat.st_uid != 0
                        or parent_stat.st_mode & 0o077
                    )
                )
            ):
                raise TenantRestoreRefused("Credential delivery file is untrusted.")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TenantRestoreRefused("Credential delivery file is unavailable.") from exc
        if not isinstance(payload, dict):
            raise TenantRestoreRefused("Credential delivery file is malformed.")
        return payload
