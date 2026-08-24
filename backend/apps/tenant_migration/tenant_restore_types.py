"""Typed host contracts for Lane D Phase T.

The host supervisor owns ordering and exclusion. Provider-specific database,
scheduler, object-store and rollout implementations satisfy these narrow contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class TenantRestoreError(RuntimeError):
    pass


class TenantRestoreRefused(TenantRestoreError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    endpoint: str
    database_name: str
    database_uuid: str = ""
    database_oid: int = 0
    tls_identity: str = ""

    def durable_key(self):
        return (
            self.endpoint,
            self.database_name,
            self.database_uuid,
            self.database_oid,
            self.tls_identity,
        )


@dataclass(frozen=True, slots=True)
class PrivilegeFacts:
    probed: bool
    can_create_database: bool
    can_restore_schema: bool
    can_apply_ownership: bool
    can_apply_runtime_grants: bool
    can_exclude_sessions: bool


@dataclass(frozen=True, slots=True)
class SiblingPlan:
    supplied: bool
    non_routable_guaranteed: bool
    provider_guarantees_empty: bool
    planned_name: str
    planned_identity: ResourceIdentity | None = None


@dataclass(frozen=True, slots=True)
class ArtifactPreflight:
    outer_sha256_ok: bool
    inner_sha256_ok: bool
    artifact_sha256_ok: bool
    format_ok: bool
    build_compatible: bool
    schema_compatible: bool
    postgres_compatible: bool
    encryption_mode_matches: bool
    tenant_fingerprint_matches: bool
    target_crypto_keys_ready: bool
    object_capacity_sufficient: bool
    api_approval_valid: bool


@dataclass(frozen=True, slots=True)
class TopologyPreflight:
    adapter_supported: bool
    pointer_compare_and_swap: bool
    exact_current_identity: ResourceIdentity | None
    scheduler_mode: str
    cloud_config_digest_matches: bool = True
    static_config_initialized: bool = True
    complete_writer_set: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StaticPreflight:
    artifact: ArtifactPreflight
    topology: TopologyPreflight
    privileges: PrivilegeFacts
    sibling: SiblingPlan
    source_identity: ResourceIdentity
    scratch_identity: ResourceIdentity | None = None


@dataclass(frozen=True, slots=True)
class SiblingResource:
    identity: ResourceIdentity
    database_url: str
    empty: bool
    non_routable: bool
    created_by_this_run: bool
    owner_marker: str = ""


@dataclass(frozen=True, slots=True)
class ObjectEntry:
    bucket: str
    key: str
    sha256: str
    size: int
    member: str
    content_type: str = ""


@dataclass(frozen=True, slots=True)
class SchedulerFenceReceipt:
    scheduler_identity: str
    scheduler_generation: str
    triggers_disabled: bool
    active_invocations: int
    registered_jobs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RestoreInputs:
    run_id: str
    artifact_sha256: str
    capture_id: str
    superadmin_email: str
    object_entries: tuple[ObjectEntry, ...] = ()
    detail: dict = field(default_factory=dict)


class ArtifactAdapter(Protocol):
    def static_preflight(self, inputs: RestoreInputs) -> ArtifactPreflight: ...
    def database_dump_path(self) -> str: ...
    def object_bytes(self, entry: ObjectEntry) -> bytes: ...


class DatabaseAdapter(Protocol):
    def privilege_facts(self) -> PrivilegeFacts: ...
    def source_identity(self) -> ResourceIdentity: ...
    def sibling_plan(self) -> SiblingPlan: ...
    def allocate(self, *, fresh_after_interrupted_restore: bool) -> SiblingResource: ...
    def prove_sibling(self, sibling: SiblingResource) -> SiblingResource: ...
    def recover_sibling(self, expected: dict) -> SiblingResource: ...
    def restore(self, sibling: SiblingResource, dump_path: str) -> None: ...
    def apply_runtime_ownership_and_grants(self, sibling: SiblingResource) -> None: ...
    def cleanup(self, sibling: SiblingResource, *, successful: bool) -> str: ...
    def database_marker_matches(self, sibling: SiblingResource, expected: dict) -> bool: ...


class WriterAdapter(Protocol):
    def persist_offline(self, inputs: RestoreInputs, preflight: StaticPreflight) -> dict: ...
    def exclude_image_writers(self, writers: tuple[str, ...]) -> dict: ...
    def prove_image_writers_excluded(self, writers: tuple[str, ...]) -> bool: ...
    def clear_gates(self, sibling: SiblingResource) -> dict: ...
    def start(self, sibling: SiblingResource, generation: int) -> dict: ...


class HostMarkerAdapter(Protocol):
    def write_intent(self, operation) -> dict: ...
    def bind_database(self, database, operation) -> dict: ...


class PointerAdapter(Protocol):
    def preflight(self, *, allow_committed_cutover: bool = False) -> TopologyPreflight: ...
    def current_generation(self) -> int: ...
    def cutover_detail(self, sibling: SiblingResource) -> dict: ...
    def compare_and_swap(self, detail: dict) -> None: ...
    def record_matches(self, detail: dict) -> bool: ...


class SchedulerAdapter(Protocol):
    def stop(self, *, run_id: str, old_identity: dict, old_generation: int) -> dict: ...
    def fence(self, *, run_id: str, expected_scheduler_generation: str) -> SchedulerFenceReceipt: ...
    def status(self, *, run_id: str) -> SchedulerFenceReceipt: ...
    def restart(self, *, run_id: str, new_identity: dict, new_generation: int) -> dict: ...
    def readiness(self, *, run_id: str, new_identity: dict, new_generation: int) -> dict: ...


class TargetAdapter(Protocol):
    def establish(self, sibling: SiblingResource, inputs: RestoreInputs) -> dict: ...
    def reissue_api_clients(self, sibling: SiblingResource, inputs: RestoreInputs) -> dict: ...
    def create_superadmin(self, sibling: SiblingResource, inputs: RestoreInputs) -> dict: ...
    def verify_activation(self, sibling: SiblingResource, inputs: RestoreInputs) -> dict: ...
    def set_normal(self, sibling: SiblingResource) -> dict: ...


class ObjectStoreAdapter(Protocol):
    def reserve_prefix(self, prefix: str) -> dict: ...
    def digest(self, bucket: str, key: str) -> tuple[int, str] | None: ...
    def put(self, entry: ObjectEntry, payload: bytes) -> None: ...
    def delete(self, bucket: str, key: str) -> None: ...
