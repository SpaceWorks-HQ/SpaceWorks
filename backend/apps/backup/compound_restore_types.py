"""Typed boundaries for Lane E's host-owned compound restore."""

from dataclasses import dataclass
from typing import Protocol

from apps.tenant_migration.tenant_restore_types import (
    ResourceIdentity,
    SiblingResource,
)


class CompoundRestoreRefused(RuntimeError):
    """A fail-closed refusal safe to show to a host operator."""


def require_complete_live_identity(identity):
    if not isinstance(identity, ResourceIdentity):
        raise CompoundRestoreRefused(
            "The restored candidate identity query returned an invalid type."
        )
    durable = identity.durable_key()
    if (
        len(durable) != 5
        or not all(isinstance(value, str) for value in durable[:3])
        or not all(durable[:3])
        or type(durable[3]) is not int
        or durable[3] <= 0
        or not isinstance(durable[4], str)
    ):
        raise CompoundRestoreRefused(
            "The restored candidate has no complete queried database identity."
        )
    return identity


@dataclass(frozen=True, slots=True)
class CompoundRestoreInputs:
    run_id: str
    capture_id: str
    artifact_sha256: str
    encrypted_file: str
    bundle: str
    manifest_file: str
    continuity_secrets_file: str
    expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CompoundTopologyFacts:
    path: str
    atomic_pointer_swap: bool
    durable_generation: bool
    identity_query: bool
    complete_writer_rollout: bool
    safe_sibling_lifecycle: bool
    writer_set: tuple[str, ...]
    authoritative_database_url: str = "host-pointer"
    external_journalled_swap: bool = False


class CompoundArtifactAdapter(Protocol):
    def database_dump_path(self) -> str: ...
    def main_object_plan(self, manifest: dict) -> tuple[dict, ...]: ...


class CompoundDatabaseAdapter(Protocol):
    def preflight(self) -> dict: ...
    def allocate(self, *, fresh_after_interrupted_restore: bool) -> SiblingResource: ...
    def prove_sibling(self, sibling: SiblingResource) -> SiblingResource: ...
    def recover_sibling(self, expected: dict) -> SiblingResource: ...
    def restore(self, sibling: SiblingResource, dump_path: str) -> None: ...
    def apply_runtime_ownership_and_grants(self, sibling: SiblingResource) -> dict: ...
    def apply_grant_state(self, sibling: SiblingResource, state: str) -> dict: ...
    def query_identity(self, sibling: SiblingResource) -> ResourceIdentity: ...
    def marker_identity(self, sibling: SiblingResource): ...
    def owns(self, sibling: SiblingResource, proof: dict) -> bool: ...
    def cleanup(self, sibling: SiblingResource, *, successful: bool) -> str: ...


class CompoundTargetAdapter(Protocol):
    def rehydrate(self, sibling: SiblingResource, inputs, manifest: dict) -> dict: ...
    def install_enforcement(self, sibling: SiblingResource, inputs, manifest: dict) -> dict: ...
    def verify_catalog(self, sibling: SiblingResource, inputs, manifest: dict) -> dict: ...
    def prepare_quarantine(self, sibling: SiblingResource, inputs, manifest: dict) -> dict: ...
    def verify_quarantine(self, sibling: SiblingResource, inputs, manifest: dict) -> dict: ...
    def acknowledge_recovery(self, sibling: SiblingResource, inputs) -> dict: ...


class CompoundWriterAdapter(Protocol):
    def persist_offline(self, inputs, topology: CompoundTopologyFacts) -> dict: ...
    def exclude(self, writers: tuple[str, ...]) -> dict: ...
    def prove_excluded(self, writers: tuple[str, ...]) -> bool: ...
    def start_candidate_backend(self, sibling: SiblingResource, *, migrate: bool) -> dict: ...
    def start_normal(self, sibling: SiblingResource, writers: tuple[str, ...]) -> dict: ...


class CompoundPointerAdapter(Protocol):
    def preflight(
        self, *, allow_committed_cutover: bool = False
    ) -> CompoundTopologyFacts: ...
    def current_generation(self) -> int: ...
    def cutover_detail(self, sibling: SiblingResource) -> dict: ...
    def compare_and_swap(self, detail: dict) -> None: ...
    def record_matches(self, detail: dict, *, rolled_back: bool = False) -> bool: ...
    def rollback(self, detail: dict) -> None: ...


class CompoundObjectAdapter(Protocol):
    def plan_main(self, artifact, manifest: dict) -> tuple[dict, ...]: ...
    def restore_main(
        self, artifact, manifest: dict, effects: tuple[dict, ...]
    ) -> tuple[dict, ...]: ...
    def rollback(self, effects: tuple[dict, ...]) -> tuple[dict, ...]: ...


class HostCapabilityAdapter(Protocol):
    def validate(self, *, inputs, manifest: dict, topology: CompoundTopologyFacts) -> dict: ...
