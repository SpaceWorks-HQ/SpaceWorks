"""Ephemeral age decryption; carried DEKs are never written to plaintext disk."""

import base64
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import uuid

from django.conf import settings

from apps.backup.archive_builder import _require_binary

from .insertion_errors import ArchiveFormatError

MAX_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024 * 1024


def stage_encrypted_upload(upload):
    root = Path(settings.BACKUP_OPS_DIR, "tenant-imports")
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise ArchiveFormatError("The encrypted migration archive could not be staged.") from exc
    path = root / f"{uuid.uuid4()}.tar.age"
    total = 0
    try:
        with path.open("xb") as output:
            for chunk in upload.chunks():
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ArchiveFormatError("The encrypted migration archive is too large.")
                output.write(chunk)
        path.chmod(0o600)
        return path
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise ArchiveFormatError("The encrypted migration archive could not be staged.") from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise


@contextmanager
def decrypted_archive(encrypted_path):
    identity = settings.TENANT_MIGRATION_AGE_IDENTITY_FILE
    if not identity:
        raise ArchiveFormatError("The target age identity is not configured.")
    try:
        _require_binary("age")
    except RuntimeError as exc:
        raise ArchiveFormatError("The age decryptor is unavailable.") from exc
    tempdir = tempfile.TemporaryDirectory(prefix="spaceworks-import-")
    root = Path(tempdir.name, "archive")
    root.mkdir()
    try:
        process = subprocess.Popen(
            ["age", "--decrypt", "-i", identity, str(encrypted_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        tempdir.cleanup()
        raise ArchiveFormatError("The age decryptor could not be started.") from exc
    carried = None
    seen, total_size = set(), 0
    try:
        if process.stdout is None:
            raise ArchiveFormatError("The age decrypt stream was not created.")
        with tarfile.open(fileobj=process.stdout, mode="r|") as bundle:
            for member in bundle:
                if not member.isfile():
                    if member.isdir():
                        continue
                    raise ArchiveFormatError("The migration archive contains a link or device.")
                relative = _safe_relative_path(member.name)
                key = relative.as_posix()
                if key in seen:
                    raise ArchiveFormatError("The migration archive contains a duplicate path.")
                seen.add(key)
                if member.size > MAX_MEMBER_BYTES:
                    raise ArchiveFormatError("A migration archive member is too large.")
                total_size += member.size
                if total_size > MAX_ARCHIVE_BYTES:
                    raise ArchiveFormatError("The migration archive is too large.")
                source = bundle.extractfile(member)
                if source is None:
                    raise ArchiveFormatError("An archive member could not be read.")
                if key == "keys/deks.json":
                    carried = _decode_keys(source.read())
                    continue
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
        if process.wait() != 0:
            raise ArchiveFormatError("The encrypted migration archive could not be decrypted.")
        if carried is None:
            raise ArchiveFormatError("The migration archive has no carried-key payload.")
        yield root, carried
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        tempdir.cleanup()


def _safe_relative_path(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ArchiveFormatError("The migration archive contains an unsafe path.")
    return path


def _decode_keys(payload):
    try:
        values = json.loads(payload)["keys"]
        records = []
        for value in values:
            record = dict(value)
            if "dek_base64" in record:
                record["dek"] = base64.b64decode(
                    record.pop("dek_base64"), validate=True
                )
            records.append(record)
        return tuple(records)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ArchiveFormatError("The carried-key payload is invalid.") from exc
