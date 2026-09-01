"""N-way object ownership planning and byte-level closure proofs."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from apps.backup.digests import sha256_file
from apps.backup.object_ownership_registry import ReferencePolicy
from apps.backup.recipient_selection import BackupBuildError


MAIN_COMPONENT = "main"


def slice_component(makerspace_id):
    return f"slice:{int(makerspace_id)}"


@dataclass(frozen=True)
class ObjectReference:
    bucket_kind: str
    object_key: str
    site: str
    candidate_owner: str | None
    canonical_makerspace_id: int | None
    module_key: str
    coordination_policy: str
    coordination_makerspace_id: int | None
    retention_state: str = "live"
    object_expired_at: str = ""
    expired_size_bytes: int | None = None


@dataclass(frozen=True)
class CapturedObject:
    size: int
    sha256: str
    retention_state: str = "live"
    object_expired_at: str = ""
    expired_size_bytes: int | None = None


class ObjectOwnershipPlan:
    """Immutable source references plus progressively bound capture facts."""

    def __init__(self, references, sovereign_makerspace_ids):
        self.references = tuple(references)
        self.sovereign_makerspace_ids = tuple(sorted(sovereign_makerspace_ids))
        grouped = defaultdict(list)
        for reference in self.references:
            grouped[(reference.bucket_kind, reference.object_key)].append(reference)
        self.multimap = {key: tuple(value) for key, value in grouped.items()}
        self._captured = {}
        self._roots = {}
        self._packaged_owner = {}
        self._validate_candidates()

    def _validate_candidates(self):
        for identity, references in self.multimap.items():
            states = {item.retention_state for item in references}
            if states - {"live", "expired"} or len(states) != 1:
                raise BackupBuildError(
                    "One object reference has inconsistent retention state."
                )
            candidates = {
                item.candidate_owner for item in references if item.candidate_owner
            }
            candidates.update(
                MAIN_COMPONENT for item in references
                if item.coordination_policy
                == ReferencePolicy.PACKAGE_MAIN_COORDINATION
            )
            if len(candidates) > 1:
                raise BackupBuildError(
                    "One captured object has more than one canonical component owner."
                )
            for item in references:
                if not item.candidate_owner and not item.coordination_policy:
                    raise BackupBuildError(
                        "A source object reference has no ownership disposition."
                    )

    def closure(self, component):
        result = {"private": {}, "public_image": {}}
        for (bucket_kind, key), references in sorted(self.multimap.items()):
            if not self._is_packaged_by(references, component):
                continue
            modules = sorted({item.module_key for item in references if item.module_key})
            makerspaces = sorted({
                item.canonical_makerspace_id for item in references
                if item.canonical_makerspace_id is not None
            })
            result[bucket_kind][key] = {
                "canonical_component": component,
                "makerspace_id": makerspaces[0] if len(makerspaces) == 1 else None,
                "module_key": modules[0] if len(modules) == 1 else "",
            }
            if references[0].retention_state == "expired":
                result[bucket_kind][key].update(
                    retention_state="expired",
                    object_expired_at=references[0].object_expired_at,
                    expired_size_bytes=references[0].expired_size_bytes,
                )
        return result

    @staticmethod
    def _is_packaged_by(references, component):
        return any(
            item.candidate_owner == component
            or (
                component == MAIN_COMPONENT
                and item.coordination_policy
                == ReferencePolicy.PACKAGE_MAIN_COORDINATION
            )
            for item in references
        )

    def bind_component(self, component, root, manifest):
        """Bind captured ledgers once, proving reference/manifest/byte equality."""
        expected = {
            identity for identity, references in self.multimap.items()
            if self._is_packaged_by(references, component)
        }
        actual = {}
        for item in manifest:
            try:
                identity = (item["bucket_kind"], item["key"])
            except (KeyError, TypeError) as exc:
                raise BackupBuildError("An object manifest entry is malformed.") from exc
            if identity in actual:
                raise BackupBuildError("An object manifest repeats a physical byte.")
            actual[identity] = item
        if set(actual) != expected:
            raise BackupBuildError(
                "Object reference and component manifest closure differ."
            )

        captured = {}
        root = Path(root)
        for identity, item in actual.items():
            if item.get("canonical_component") != component:
                raise BackupBuildError("An object manifest names the wrong component owner.")
            previous = self._packaged_owner.get(identity)
            if previous is not None and previous != component:
                raise BackupBuildError("A physical object byte was packaged by two components.")
            references = self.multimap[identity]
            retention_state = references[0].retention_state
            path = root / identity[0] / identity[1]
            if retention_state == "expired":
                if (
                    item.get("retention_state") != "expired"
                    or item.get("object_expired_at")
                    != references[0].object_expired_at
                    or item.get("expired_size_bytes")
                    != references[0].expired_size_bytes
                    or path.exists()
                ):
                    raise BackupBuildError(
                        "An expired object tombstone is inconsistent with its source state."
                    )
                size, digest = 0, ""
            else:
                if item.get("retention_state") is not None:
                    raise BackupBuildError("A live object was replaced by a tombstone.")
                try:
                    size = path.stat().st_size
                    digest = sha256_file(path)
                except OSError as exc:
                    raise BackupBuildError("A captured object byte is missing.") from exc
                if size != item.get("size") or digest != item.get("sha256"):
                    raise BackupBuildError(
                        "A packaged object differs from its immutable capture ledger."
                    )
            self._packaged_owner[identity] = component
            captured[identity] = CapturedObject(
                size=size,
                sha256=digest,
                retention_state=retention_state,
                object_expired_at=references[0].object_expired_at,
                expired_size_bytes=references[0].expired_size_bytes,
            )
        if component in self._captured:
            raise BackupBuildError("An object component was bound more than once.")
        self._captured[component] = captured
        self._roots[component] = root

    def verify_component(self, component, manifest):
        captured = self._captured.get(component)
        if captured is None:
            raise BackupBuildError("An object component lacks immutable capture facts.")
        actual = {}
        for item in manifest:
            identity = (item.get("bucket_kind"), item.get("key"))
            if identity in actual:
                raise BackupBuildError("An object manifest repeats a physical byte.")
            actual[identity] = item
        if set(actual) != set(captured):
            raise BackupBuildError("An object manifest changed after capture.")
        for identity, fact in captured.items():
            item = actual[identity]
            path = self._roots[component] / identity[0] / identity[1]
            if fact.retention_state == "expired":
                byte_mismatch = path.exists()
            else:
                try:
                    byte_mismatch = (
                        path.stat().st_size != fact.size
                        or sha256_file(path) != fact.sha256
                    )
                except OSError:
                    byte_mismatch = True
            if (
                item.get("size") != fact.size
                or item.get("sha256") != fact.sha256
                or item.get("retention_state", "live") != fact.retention_state
                or item.get("object_expired_at", "") != fact.object_expired_at
                or item.get("expired_size_bytes") != fact.expired_size_bytes
                or byte_mismatch
            ):
                raise BackupBuildError(
                    "A packaged object differs from its immutable capture ledger."
                )

    def assert_complete(self):
        expected_components = {MAIN_COMPONENT} | {
            slice_component(value) for value in self.sovereign_makerspace_ids
        }
        if set(self._captured) != expected_components:
            raise BackupBuildError("Not every object component closure was captured.")
        for component in expected_components:
            immutable_manifest = [
                {"bucket_kind": kind, "key": key, "size": fact.size,
                 "sha256": fact.sha256, "retention_state": fact.retention_state}
                for (kind, key), fact in self._captured[component].items()
            ]
            # Re-read bytes against facts even though the caller no longer holds a
            # mutable manifest entry for this internal check.
            for item in immutable_manifest:
                fact = self._captured[component][(item["bucket_kind"], item["key"])]
                path = self._roots[component] / item["bucket_kind"] / item["key"]
                if fact.retention_state == "expired":
                    mismatch = path.exists()
                else:
                    try:
                        mismatch = (
                            path.stat().st_size != fact.size
                            or sha256_file(path) != fact.sha256
                        )
                    except OSError:
                        mismatch = True
                if mismatch:
                    raise BackupBuildError(
                        "A packaged object changed after immutable capture."
                    )


def build_object_ownership_plan(sovereign_makerspace_ids):
    """Compatibility entrypoint; snapshot extraction lives in its own module."""
    from apps.backup.object_reference_capture import build_object_ownership_plan as build

    return build(sovereign_makerspace_ids)
