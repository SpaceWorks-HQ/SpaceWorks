"""Lane E compound capture, verified slice sealing, and readable-main routing."""

from pathlib import Path
import shutil
import uuid

from django.db import connection

from apps.backup.compound_recipients import (
    FrozenSlice,
    frozen_population,
    frozen_slices,
    predecessor_snapshot,
)
from apps.backup.compound_slice_build import build_unsealed_slice, seal_verified_slice
from apps.backup.digests import sha256_file
from apps.backup.main_projection import project_readable_main_dump
from apps.backup.main_projection_registry import table_rules
from apps.backup.main_projection_verification import build_expected_ledger
from apps.backup.object_ownership import MAIN_COMPONENT, slice_component
from apps.backup.physical_catalog import catalog_digest, physical_catalog_ledger
from apps.backup.postgres_client import server_major
from apps.backup.reconstruction_verifier import verify_reconstruction
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.backup.source_reservations import capture_source_reservations
from apps.backup.source_verifier import verify_and_sign_source_partition
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
        self.unsealed_slices = []
        self.frozen_slices = ()
        self.verified_makerspace_ids = set()
        self.expected_main_ledger = None
        self.expected_full_ledger = None
        self.source_catalog_ledger = None
        self.source_catalog_digest = ""
        self.reservation_capture = None
        self.source_partition_proof = None
        self.source_dump_sha256 = ""
        self.source_database_identity = ""
        self.source_server_identity = ""
        self.object_plan = None
        self.frozen_population = ()
        self.frozen_population_ids = ()
        self.predecessor_snapshot = {}
        self.user_closure_entries = set()
        self.user_closure_digest = user_closure_digest(())
        self.verifier_root = self.root.parent / f".lane-e-verifier-{self.capture_id}"

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
        self.source_dump_sha256 = sha256_file(self.root / "database.dump")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_setting('server_version_num'), "
                "(pg_catalog.pg_control_system()).system_identifier"
            )
            database_name, version, system_identifier = cursor.fetchone()
        self.source_database_identity = database_name
        self.source_server_identity = f"postgresql:{version}:{system_identifier}"
        makerspace_ids = tuple(
            item.makerspace_id for item in self.frozen_slices
        )
        rules = table_rules()
        self.source_catalog_ledger = physical_catalog_ledger("default")
        self.source_catalog_digest = catalog_digest(self.source_catalog_ledger)
        self.reservation_capture = capture_source_reservations(
            "default",
            rules,
            {item.makerspace_id: item.slice_id for item in self.frozen_slices},
            postgres_major=server_major(),
        )
        self.expected_main_ledger = build_expected_ledger(
            "default", rules, makerspace_ids,
            sequence_facts=self.reservation_capture.sequence_facts,
        )
        self.expected_full_ledger = build_expected_ledger(
            "default", rules, (),
            sequence_facts=self.reservation_capture.sequence_facts,
        )

    def capture_from_snapshot(
        self, *, tenant_payload, capture_objects, write_json, object_plan
    ):
        if self.expected_main_ledger is None:
            raise BackupBuildError("Compound capture was not prepared in the snapshot.")
        self.object_plan = object_plan
        self.verifier_root.mkdir(parents=True, exist_ok=False)
        for item in self.frozen_slices:
            unsealed = build_unsealed_slice(
                item,
                work_root=self.verifier_root,
                tenant_payload=tenant_payload,
                capture_objects=capture_objects,
                write_json=write_json,
                object_plan=object_plan,
                modes=self.modes,
                archive_format=COMPOUND_ARCHIVE_FORMAT,
            )
            self.unsealed_slices.append(unsealed)
            self.user_closure_entries.update(unsealed.user_closure_entries)
            self.verified_makerspace_ids.add(item.makerspace_id)
        object_plan.assert_complete()
        self.reservation_capture = self.reservation_capture.bind_object_plan(
            object_plan,
            {item.makerspace_id: item.slice_id for item in self.frozen_slices},
        )
        self.require_verified_slice_coverage()
        self.user_closure_digest = user_closure_digest(self.user_closure_entries)

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
        emitted = {item.frozen.makerspace_id for item in self.unsealed_slices}
        if self.slice_entries:
            emitted = {item.get("makerspace_id") for item in self.slice_entries}
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
                sequence_facts=self.reservation_capture.sequence_facts,
            )
            reconstruction_pass = verify_reconstruction(
                self.root / "database.dump",
                self.unsealed_slices,
                table_rules(),
                self.expected_full_ledger,
                self.reservation_capture,
                postgres_major=server_major(),
            )
            self.slice_entries = [
                seal_verified_slice(item, self.root / "slices", self.verifier_root)
                for item in self.unsealed_slices
            ]
            if self.object_plan is None:
                raise BackupBuildError("Compound object ownership proof is missing.")
            self.object_plan.verify_component(
                MAIN_COMPONENT, manifest["storage"]["objects"]
            )
            _verify_sealed_slices(self.root, self.slice_entries)
            self.source_partition_proof = verify_and_sign_source_partition(
                self,
                detailed_manifest=manifest,
                reconstruction_pass=reconstruction_pass,
            )
            result = dict(manifest)
        finally:
            shutil.rmtree(build_root, ignore_errors=True)
            shutil.rmtree(self.verifier_root, ignore_errors=True)
        covered = [
            value for value in result["covered_makerspace_ids"]
            if value not in makerspace_ids
        ]
        result["covered_makerspace_ids"] = covered
        result["excluded_makerspace_ids"] = list(makerspace_ids)
        result["partial"] = bool(makerspace_ids)
        return result

    def cleanup_verifier_material(self):
        shutil.rmtree(self.verifier_root, ignore_errors=True)


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
