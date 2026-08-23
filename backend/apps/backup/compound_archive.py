"""Lane E compound capture, verified slice sealing, and readable-main routing."""

from pathlib import Path
import json
import shutil
import subprocess
import tarfile
import uuid

from apps.backup.compound_recipients import (
    FrozenSlice,
    frozen_population,
    frozen_slices,
    predecessor_snapshot,
)
from apps.backup.dek_rewrap import enumerate_staged_deks, seal_staged_deks
from apps.backup.digests import build_content_ledger, sha256_file
from apps.backup.main_projection import project_readable_main_dump
from apps.backup.main_projection_inverse import boundary_deltas
from apps.backup.main_projection_registry import table_rules
from apps.backup.main_projection_verification import build_expected_ledger
from apps.backup.object_ownership import MAIN_COMPONENT, slice_component
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.backup.slice_verification import verify_unsealed_slice
from apps.backup.user_closure import user_closure_digest


COMPOUND_ARCHIVE_FORMAT = "spaceworks-lane-e-e3-compound-v1"


class CompoundCapture:
    def __init__(self, *, archive, root, modes, platform_recipients):
        self.archive = archive
        self.capture_id = uuid.uuid4()
        self.root = Path(root)
        self.modes = modes
        self.platform_recipients = frozenset(
            entry["public_recipient"] for entry in platform_recipients
        )
        self.slice_entries = []
        self.frozen_slices = ()
        self.verified_makerspace_ids = set()
        self.expected_main_ledger = None
        self.object_plan = None
        self.frozen_population = ()
        self.frozen_population_ids = ()
        self.predecessor_snapshot = {}
        self.user_closure_entries = set()
        self.user_closure_digest = user_closure_digest(())

    def prepare_from_snapshot(self):
        if self.frozen_slices:
            raise BackupBuildError("Compound capture was prepared more than once.")
        self.frozen_population = frozen_population()
        self.predecessor_snapshot = predecessor_snapshot()
        self.frozen_population_ids = tuple(
            item["makerspace_id"] for item in self.frozen_population
        )
        self.frozen_slices = frozen_slices(
            self.capture_id, self.platform_recipients, self.frozen_population
        )
        makerspace_ids = tuple(
            item.makerspace_id for item in self.frozen_slices
        )
        self.expected_main_ledger = build_expected_ledger(
            "default", table_rules(), makerspace_ids
        )

    def capture_from_snapshot(
        self, *, tenant_payload, capture_objects, write_json, object_plan
    ):
        if self.expected_main_ledger is None:
            raise BackupBuildError("Compound capture was not prepared in the snapshot.")
        self.object_plan = object_plan
        slices_root = self.root / "slices"
        work_root = self.root / ".slice-build"
        try:
            for item in self.frozen_slices:
                self.slice_entries.append(
                    self._seal_slice(
                        item,
                        slices_root=slices_root,
                        work_root=work_root,
                        tenant_payload=tenant_payload,
                        capture_objects=capture_objects,
                        write_json=write_json,
                        object_plan=object_plan,
                    )
                )
            object_plan.assert_complete()
            self.require_verified_slice_coverage()
            self.user_closure_digest = user_closure_digest(
                self.user_closure_entries
            )
        finally:
            shutil.rmtree(work_root, ignore_errors=True)

    def _seal_slice(
        self,
        item,
        *,
        slices_root,
        work_root,
        tenant_payload,
        capture_objects,
        write_json,
        object_plan,
    ):
        plaintext = work_root / item.slice_id
        rows_root = plaintext / "rows"
        tenant_payload(item.makerspace_id, rows_root)
        component = slice_component(item.makerspace_id)
        object_keys = object_plan.closure(component)
        objects = capture_objects(
            plaintext / "objects", object_keys, self.modes
        )
        object_plan.bind_component(component, plaintext / "objects", objects)
        closure_entries = self._user_closure(plaintext)
        self.user_closure_entries.update(closure_entries)
        write_json(
            plaintext / "user-closure-ledger.json",
            [{
                "disposition": disposition,
                "source_user_pk": int(source_pk),
                "reason_code": reason_code,
            } for disposition, source_pk, reason_code in closure_entries],
        )
        staged_deks = enumerate_staged_deks(item.makerspace_id)
        sealed_deks = seal_staged_deks(
            staged_deks, item.public_recipients, plaintext / "keys" / "deks"
        )
        write_json(
            plaintext / "inverse" / "boundary-deltas.json",
            boundary_deltas(item.makerspace_id),
        )
        write_json(
            plaintext / "slice-manifest.json",
            {
                "format": COMPOUND_ARCHIVE_FORMAT,
                "slice_id": item.slice_id,
                "makerspace_id": item.makerspace_id,
                "recipient_fingerprints": list(item.recipient_fingerprints),
                "custody_state": item.custody_state,
                "storage": {"objects": objects},
                "sealed_deks": sealed_deks,
            },
        )
        verify_unsealed_slice(
            item.makerspace_id, plaintext, objects,
            staged_deks=staged_deks, sealed_deks=sealed_deks,
        )
        self.verified_makerspace_ids.add(item.makerspace_id)
        slices_root.mkdir(parents=True, exist_ok=True)
        plain_tar = work_root / f"{item.slice_id}.tar"
        encrypted = slices_root / f"{item.slice_id}.tar.age"
        with tarfile.open(plain_tar, "w") as bundle:
            bundle.add(plaintext, arcname=".")
        command = ["age"]
        for public_recipient in item.public_recipients:
            command += ["-r", public_recipient]
        command += ["-o", str(encrypted), str(plain_tar)]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BackupBuildError(
                "A sovereign archive slice could not be encrypted."
            ) from exc
        content_ledger = build_content_ledger(plaintext)
        return {
            "component_id": item.slice_id,
            "slice_id": item.slice_id,
            "makerspace_id": item.makerspace_id,
            "path": f"slices/{item.slice_id}.tar.age",
            "size_bytes": encrypted.stat().st_size,
            "ciphertext_sha256": sha256_file(encrypted),
            "recipient_fingerprints": list(item.recipient_fingerprints),
            "custody_state": item.custody_state,
            "object_ledger_count": len(objects),
            "object_ledger_digest": _json_digest(objects),
            "content_ledger_count": len(content_ledger),
            "content_ledger_digest": _json_digest(content_ledger),
        }

    @staticmethod
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

    def promotion_snapshot(self):
        slices = {item.makerspace_id: item for item in self.frozen_slices}
        return {
            **self.predecessor_snapshot,
            "retained": [
                {
                    **item,
                    "custody_state": (
                        slices[item["makerspace_id"]].custody_state
                        if item["makerspace_id"] in slices else None
                    ),
                    "recipients": [
                        {"pk": pk, "fingerprint": fingerprint}
                        for pk, fingerprint in (
                            slices[item["makerspace_id"]].recipient_rows
                            if item["makerspace_id"] in slices else ()
                        )
                    ],
                }
                for item in self.frozen_population
            ]
        }

    def require_verified_slice_coverage(self):
        expected = {item.makerspace_id for item in self.frozen_slices}
        emitted = {
            entry.get("makerspace_id")
            for entry in self.slice_entries
            if isinstance(entry, dict)
        }
        if expected != emitted or expected != self.verified_makerspace_ids:
            raise BackupBuildError(
                "Readable-main exclusion requires one verified slice per sovereign makerspace."
            )

    def project_readable_main(self, manifest):
        self.require_verified_slice_coverage()
        if self.expected_main_ledger is None:
            raise BackupBuildError("Readable-main verification ledger is missing.")
        makerspace_ids = tuple(item.makerspace_id for item in self.frozen_slices)
        build_root = self.root / ".main-build"
        source_dump = build_root / "source.dump"
        build_root.mkdir()
        (self.root / "database.dump").replace(source_dump)
        try:
            project_readable_main_dump(
                source_dump,
                self.root / "database.dump",
                makerspace_ids,
                self.expected_main_ledger,
            )
            if self.object_plan is None:
                raise BackupBuildError("Compound object ownership proof is missing.")
            self.object_plan.verify_component(
                MAIN_COMPONENT, manifest["storage"]["objects"]
            )
            _verify_sealed_slices(self.root, self.slice_entries)
            result = dict(manifest)
        finally:
            shutil.rmtree(build_root, ignore_errors=True)
        covered = [
            value for value in result["covered_makerspace_ids"]
            if value not in makerspace_ids
        ]
        result["covered_makerspace_ids"] = covered
        result["excluded_makerspace_ids"] = list(makerspace_ids)
        result["partial"] = bool(makerspace_ids)
        return result


def add_slice_metadata(manifest, *, slices, recipients):
    """Add sealed-slice routing facts without changing the restore payload layout."""
    result = dict(manifest)
    result.pop("recipients", None)
    result["recipient_fingerprints"] = sorted(
        fingerprint_for(entry["public_recipient"]) for entry in recipients
    )
    result["slices"] = list(slices)
    return result


def _verify_sealed_slices(root, entries):
    for entry in entries:
        path = root / entry["path"]
        if (
            path.stat().st_size != entry["size_bytes"]
            or sha256_file(path) != entry["ciphertext_sha256"]
        ):
            raise BackupBuildError("A sealed sovereign slice failed ciphertext verification.")


def _json_digest(value):
    import hashlib

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
