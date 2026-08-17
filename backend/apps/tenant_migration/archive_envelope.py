"""Build a tenant migration tar stream directly inside an age envelope."""

import base64
import io
import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace

from django.conf import settings
from django.utils import timezone

from apps.backup.archive_builder import _build_info, _require_binary
from apps.backup.digests import build_content_ledger, sha256_bytes, sha256_file
from apps.data_export.runner import build_archive
from apps.data_export.types import Fidelity
from apps.encryption.cache import dek_cache_disabled
from apps.tenant_migration.keys import collect_source_keys
from apps.tenant_migration.deployment_keys import public_deployment_identity
from apps.tenant_migration.preflight import SourcePreflightError, run_source_preflight
from apps.tenant_migration.protocol_errors import ClosureAdmissionError
from apps.tenant_migration.source_gate import quiesced_snapshot

FORMAT = "spaceworks-tenant-migration-v1"
FORMAT_VERSION = 1


class MigrationArchiveError(RuntimeError):
    pass


def build_tenant_migration_archive(
    makerspace, output, *, gate_owner_id=None, gate_fencing_token=None,
    actor=None, sleep=None, disclosure_approval=None, recipient=None,
):
    """Return ``(encrypted_path, manifest, encrypted_sha256)`` for one tenant."""
    output = Path(output).expanduser().resolve()
    if disclosure_approval is None and hasattr(makerspace, "_meta"):
        disclosure_approval = _current_approval(makerspace)
    if output.exists():
        raise MigrationArchiveError(f"Output path already exists: {output}")
    recipient = recipient or settings.BACKUP_AGE_RECIPIENT
    if not recipient:
        raise MigrationArchiveError(
            "BACKUP_AGE_RECIPIENT is required before tenant migration export can run."
        )
    try:
        _require_binary("age")
    except RuntimeError as exc:
        raise MigrationArchiveError(str(exc)) from exc

    # This context clears cache-owned DEK references and prevents either preflight
    # or collection from repopulating the process-wide cache.
    gate_kwargs = {
        "owner_id": gate_owner_id,
        "fencing_token": gate_fencing_token,
    }
    if sleep is not None:
        gate_kwargs["sleep"] = sleep
    with dek_cache_disabled(), quiesced_snapshot(
        makerspace, actor, **gate_kwargs
    ) as gate_lease:
        try:
            preflight = run_source_preflight(makerspace)
            keys = collect_source_keys(makerspace)
            export_root, export_manifest, tempdir = build_archive(
                _portable_job(makerspace, disclosure_approval),
                package=False,
                existing_snapshot=True,
            )
            try:
                key_payload = _serialize_keys(keys)
                manifest = _manifest(
                    makerspace, preflight, export_manifest, export_root, key_payload
                )
                manifest["source"]["gate"] = {
                    "owner_id": str(gate_lease.owner_id),
                    "fencing_token": gate_lease.fencing_token,
                }
                manifest_payload = _json_bytes(manifest)
                output.parent.mkdir(parents=True, exist_ok=True)
                _stream_age_archive(
                    export_root, key_payload, manifest_payload, output, recipient
                )
                return output, manifest, sha256_file(output)
            finally:
                tempdir.cleanup()
        except (MigrationArchiveError, SourcePreflightError, ClosureAdmissionError):
            raise
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise MigrationArchiveError(
                "The tenant migration archive could not be built."
            ) from exc


def _portable_job(makerspace, disclosure_approval):
    now = timezone.now()
    return SimpleNamespace(
        fidelity=Fidelity.PORTABLE.value,
        makerspace=makerspace,
        makerspace_id=makerspace.pk,
        disclosure_approval=disclosure_approval,
        deadline_at=now + timezone.timedelta(
            seconds=settings.DATA_EXPORT_DEADLINE_SECONDS
        ),
    )


def _current_approval(makerspace):
    from .admission import compute_pending_closure
    from .models_protocol import DisclosureClosureApproval

    digest = compute_pending_closure(makerspace)["digest"]
    approval = DisclosureClosureApproval.objects.filter(
        makerspace=makerspace, closure_digest=digest, revoked_at__isnull=True
    ).order_by("-approved_at").first()
    if approval is None:
        raise ClosureAdmissionError(
            "A source-superadmin disclosure approval is required for this exact closure."
        )
    return approval


def _serialize_keys(keys):
    records = []
    for key in keys:
        record = {name: value for name, value in key.items() if name != "dek"}
        if "dek" in key:
            record["dek_base64"] = base64.b64encode(key["dek"]).decode("ascii")
        records.append(record)
    return _json_bytes({"keys": records})


def _manifest(makerspace, preflight, export_manifest, root, key_payload):
    # As in Phase 5A, the ledger covers every payload member and intentionally
    # excludes the manifest itself, whose inclusion would be self-referential.
    contents = build_content_ledger(root)
    contents.append(
        {
            "path": "keys/deks.json",
            "size": len(key_payload),
            "sha256": sha256_bytes(key_payload),
        }
    )
    contents.sort(key=lambda entry: entry["path"])
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "source": {
            "makerspace": {
                "id": makerspace.pk,
                "slug": makerspace.slug,
                "name": makerspace.name,
            },
            "deployment_build": _build_info(),
            "deployment": public_deployment_identity(),
        },
        "snapshot_at": export_manifest["snapshot_at"],
        "row_counts": export_manifest.get("row_counts", {}),
        "total_rows": export_manifest.get("total_rows", 0),
        "registry_version": export_manifest.get("registry_version", ""),
        "storage_mode": preflight.storage_mode,
        "carried_keys": [
            {"version": version, "status": status}
            for version, status in preflight.carried_key_versions
        ],
        "contents": contents,
        "age_encrypted": True,
    }


def _stream_age_archive(root, key_payload, manifest_payload, output, recipient):
    # runner.build_archive normally finishes with shutil.make_archive, leaving a
    # plaintext ZIP until finally-cleanup. A hard kill could preserve it. That
    # packaging path is deliberately bypassed here, and DEKs exist only in this
    # in-memory member before tar bytes flow directly into age.
    command = ["age", "-r", recipient, "-o", str(output)]
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if process.stdin is None:
            raise OSError("age stdin pipe was not created")
        with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
            for path in sorted(item for item in Path(root).rglob("*") if item.is_file()):
                archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
            _add_bytes(archive, "keys/deks.json", key_payload)
            _add_bytes(archive, "migration-manifest.json", manifest_payload)
        process.stdin.close()
        return_code = process.wait()
        if return_code:
            raise subprocess.CalledProcessError(return_code, command)
    except (OSError, BrokenPipeError, subprocess.SubprocessError) as exc:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        output.unlink(missing_ok=True)
        raise MigrationArchiveError(
            "The age-encrypted tenant migration archive could not be built."
        ) from exc


def _add_bytes(archive, name, payload):
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mtime = 0
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(payload))


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
