"""Unsealed slice construction and post-reconstruction sealing."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

from apps.backup.dek_rewrap import enumerate_staged_deks, seal_staged_deks
from apps.backup.digests import build_content_ledger, sha256_file
from apps.backup.main_projection_inverse import boundary_deltas
from apps.backup.object_ownership import slice_component
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.slice_verification import verify_unsealed_slice


@dataclass(frozen=True)
class UnsealedSlice:
    frozen: object
    plaintext: Path
    object_manifest: tuple[dict, ...]
    staged_deks: list[object]
    sealed_deks: list[dict]


def build_unsealed_slice(
    item, *, work_root, tenant_payload, capture_objects, write_json,
    object_plan, modes, archive_format,
):
    plaintext = Path(work_root) / item.slice_id
    rows_root = plaintext / "rows"
    tenant_payload(item.makerspace_id, rows_root)
    component = slice_component(item.makerspace_id)
    object_keys = object_plan.closure(component)
    objects = capture_objects(plaintext / "objects", object_keys, modes)
    object_plan.bind_component(component, plaintext / "objects", objects)
    closure_entries = _user_closure(plaintext)
    write_json(plaintext / "user-closure-ledger.json", [
        {
            "disposition": disposition,
            "source_user_pk": int(source_pk),
            "reason_code": reason_code,
        }
        for disposition, source_pk, reason_code in closure_entries
    ])
    # W8 requires an IMMUTABLE staged enumeration: seal_staged_deks guards with a strict
    # `type(staged_rows) is not tuple`, so wrapping this in list() defeats the very invariant
    # (Lane E section 5, "Guarded W8 rewrap") that the guard exists to enforce.
    staged_deks = enumerate_staged_deks(item.makerspace_id)
    sealed_deks = list(seal_staged_deks(
        staged_deks, item.public_recipients, plaintext / "keys" / "deks"
    ))
    write_json(
        plaintext / "inverse" / "boundary-deltas.json",
        boundary_deltas(item.makerspace_id),
    )
    write_json(plaintext / "slice-manifest.json", {
        "format": archive_format,
        "slice_id": item.slice_id,
        "makerspace_id": item.makerspace_id,
        "recipient_fingerprints": list(item.recipient_fingerprints),
        "custody_state": item.custody_state,
        "storage": {"objects": objects},
        "sealed_deks": sealed_deks,
    })
    verify_unsealed_slice(
        item.makerspace_id, plaintext, objects,
        staged_deks=staged_deks, sealed_deks=sealed_deks,
    )
    return UnsealedSlice(
        frozen=item,
        plaintext=plaintext,
        object_manifest=tuple(objects),
        staged_deks=staged_deks,
        sealed_deks=sealed_deks,
    )


def seal_verified_slice(item, slices_root, work_root):
    frozen = item.frozen
    slices_root.mkdir(parents=True, exist_ok=True)
    plain_tar = Path(work_root) / f"{frozen.slice_id}.tar"
    encrypted = slices_root / f"{frozen.slice_id}.tar.age"
    with tarfile.open(plain_tar, "w") as bundle:
        bundle.add(item.plaintext, arcname=".")
    command = ["age"]
    for recipient in frozen.public_recipients:
        command += ["-r", recipient]
    command += ["-o", str(encrypted), str(plain_tar)]
    try:
        subprocess.run(
            command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupBuildError("A sovereign archive slice could not be encrypted.") from exc
    finally:
        plain_tar.unlink(missing_ok=True)
    content = build_content_ledger(item.plaintext)
    return {
        "component_id": frozen.slice_id,
        "slice_id": frozen.slice_id,
        "makerspace_id": frozen.makerspace_id,
        "path": f"slices/{frozen.slice_id}.tar.age",
        "size_bytes": encrypted.stat().st_size,
        "ciphertext_sha256": sha256_file(encrypted),
        "recipient_fingerprints": list(frozen.recipient_fingerprints),
        "custody_state": frozen.custody_state,
        "object_ledger_count": len(item.object_manifest),
        "object_ledger_digest": _json_digest(item.object_manifest),
        "content_ledger_count": len(content),
        "content_ledger_digest": _json_digest(content),
    }


def _user_closure(plaintext):
    path = plaintext / "rows" / "global_user_references.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupBuildError("A sovereign user-closure ledger is unreadable.") from exc
    return tuple(sorted({
        ("stubbed", str(item["id"]), "sovereign-global-user-reference")
        for item in values
    }))


def _json_digest(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
