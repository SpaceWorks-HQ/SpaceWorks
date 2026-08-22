"""Lane E compound capture, verified slice sealing, and readable-main routing."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tarfile
import uuid

from apps.backup.digests import sha256_file
from apps.backup.main_projection import project_readable_main_dump
from apps.backup.main_projection_inverse import boundary_deltas
from apps.backup.main_projection_registry import table_rules
from apps.backup.main_projection_verification import build_expected_ledger
from apps.backup.models import (
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.backup.slice_verification import verify_unsealed_slice
from apps.makerspaces.models import Makerspace


COMPOUND_ARCHIVE_FORMAT = "spaceworks-lane-e-e3-compound-v1"


@dataclass(frozen=True)
class FrozenSlice:
    makerspace_id: int
    slice_id: str
    public_recipients: tuple[str, ...]
    recipient_fingerprints: tuple[str, ...]
    custody_state: str


class CompoundCapture:
    """Build sovereign slices from the caller's repeatable-read capture."""

    def __init__(self, *, archive, root, modes, platform_recipients):
        self.archive = archive
        self.root = Path(root)
        self.modes = modes
        self.platform_recipients = frozenset(
            entry["public_recipient"] for entry in platform_recipients
        )
        self.slice_entries = []
        self.frozen_slices = ()
        self.verified_makerspace_ids = set()
        self.expected_main_ledger = None

    def capture_from_snapshot(self, *, tenant_payload, capture_objects, write_json):
        frozen = _frozen_slices(self.archive.id, self.platform_recipients)
        self.frozen_slices = frozen
        makerspace_ids = tuple(item.makerspace_id for item in frozen)
        self.expected_main_ledger = build_expected_ledger(
            "default", table_rules(), makerspace_ids
        )
        slices_root = self.root / "slices"
        work_root = self.root / ".slice-build"
        try:
            for item in frozen:
                self.slice_entries.append(
                    self._seal_slice(
                        item,
                        slices_root=slices_root,
                        work_root=work_root,
                        tenant_payload=tenant_payload,
                        capture_objects=capture_objects,
                        write_json=write_json,
                    )
                )
            self.require_verified_slice_coverage()
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
    ):
        plaintext = work_root / item.slice_id
        rows_root = plaintext / "rows"
        object_keys = tenant_payload(item.makerspace_id, rows_root)
        objects = capture_objects(
            plaintext / "objects", object_keys, self.modes
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
            },
        )
        verify_unsealed_slice(item.makerspace_id, plaintext, objects)
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
        return {
            "slice_id": item.slice_id,
            "makerspace_id": item.makerspace_id,
            "path": f"slices/{item.slice_id}.tar.age",
            "size_bytes": encrypted.stat().st_size,
            "ciphertext_sha256": sha256_file(encrypted),
            "recipient_fingerprints": list(item.recipient_fingerprints),
            "custody_state": item.custody_state,
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
        """Replace the full source dump only after slice coverage and main verification."""
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
            _verify_sealed_slices(self.root, self.slice_entries)
            result = _exclude_sovereign_objects(
                self.root, manifest, set(makerspace_ids)
            )
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


def _frozen_slices(archive_id, platform_recipients):
    # Deployment selection intentionally returns only the platform recipient;
    # slice custody is therefore resolved directly from this frozen tenant view.
    makerspace_ids = tuple(
        Makerspace.objects.filter(superadmin_access_enabled=False)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    recipient_rows = MakerspaceArchiveRecipient.objects.filter(
        makerspace_id__in=makerspace_ids,
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).order_by("makerspace_id", "pk").values_list(
        "makerspace_id", "public_recipient"
    )
    by_makerspace = {makerspace_id: [] for makerspace_id in makerspace_ids}
    for makerspace_id, public_recipient in recipient_rows:
        by_makerspace[makerspace_id].append(public_recipient)
    custody = dict(
        MakerspaceArchiveCustodyState.objects.filter(
            makerspace_id__in=makerspace_ids
        ).values_list("makerspace_id", "state")
    )

    result = []
    for makerspace_id in makerspace_ids:
        public_recipients = tuple(by_makerspace[makerspace_id])
        if not public_recipients:
            raise BackupBuildError(
                "A sovereign makerspace has no valid archive recipient."
            )
        fingerprints = tuple(sorted(
            fingerprint_for(value) for value in public_recipients
        ))
        if len(set(fingerprints)) != len(fingerprints):
            raise BackupBuildError(
                "A sovereign makerspace has duplicate archive recipients."
            )
        if platform_recipients.intersection(public_recipients):
            raise BackupBuildError(
                "A platform archive recipient cannot be used for a sovereign slice."
            )
        expected_custody = (
            MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT
            if len(public_recipients) == 1
            else MakerspaceArchiveCustodyState.State.HEALTHY
        )
        if len(public_recipients) == 1 and custody.get(makerspace_id) != expected_custody:
            raise BackupBuildError(
                "A one-recipient sovereign makerspace lacks its degraded custody state."
            )
        result.append(FrozenSlice(
            makerspace_id=makerspace_id,
            slice_id=str(uuid.uuid5(archive_id, f"sovereign-slice:{makerspace_id}")),
            public_recipients=public_recipients,
            recipient_fingerprints=fingerprints,
            custody_state=expected_custody,
        ))
    return tuple(result)


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


def _exclude_sovereign_objects(root, manifest, makerspace_ids):
    result = dict(manifest)
    storage_manifest = dict(result["storage"])
    retained = []
    for item in storage_manifest["objects"]:
        if item.get("makerspace_id") in makerspace_ids:
            path = root / "objects" / item["bucket_kind"] / item["key"]
            path.unlink(missing_ok=True)
        else:
            path = root / "objects" / item["bucket_kind"] / item["key"]
            if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
                raise BackupBuildError("Readable-main object verification failed.")
            retained.append(item)
    storage_manifest["objects"] = retained
    result["storage"] = storage_manifest
    return result
