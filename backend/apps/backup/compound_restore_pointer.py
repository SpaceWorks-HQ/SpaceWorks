"""Lane E adapters over H1's atomic file and store-native pointer primitives."""

from apps.backup.host_pointer import (
    PointerRecord,
    compare_and_swap_external,
    read_pointer,
    write_pointer_atomic,
)
from apps.tenant_migration.tenant_restore_types import ResourceIdentity

from .compound_restore_types import (
    CompoundRestoreRefused,
    CompoundTopologyFacts,
)


class FileCompoundPointer:
    def __init__(
        self, *, path, topology, current_identity, runtime_url,
        invalidate_capabilities, require_root_owned=True, crash_hook=None,
    ):
        self.path = path
        self.topology = topology
        self.current_identity = current_identity
        self.runtime_url = runtime_url
        self.invalidate_capabilities = invalidate_capabilities
        self.require_root_owned = require_root_owned
        self.crash_hook = crash_hook

    def _current(self):
        return read_pointer(
            self.path, require_root_owned=self.require_root_owned
        )

    def preflight(self, *, allow_committed_cutover=False):
        self._current()
        identity = self.current_identity()
        if not _queried_identity(identity):
            raise CompoundRestoreRefused(
                "The file-pointer path could not query the live database identity."
            )
        return self.topology

    def current_generation(self):
        return self._current().generation

    def cutover_detail(self, sibling):
        current = self._current()
        return {
            "old_database_url": current.database_url,
            "new_database_url": self.runtime_url(sibling),
            "old_generation": current.generation,
            "new_generation": current.generation + 1,
            "new_database_identity": list(sibling.identity.durable_key()),
        }

    def compare_and_swap(self, detail):
        write_pointer_atomic(
            self.path,
            PointerRecord(
                detail["new_database_url"], detail["new_generation"]
            ),
            expected_generation=detail["old_generation"],
            invalidate=self.invalidate_capabilities,
            crash_hook=self.crash_hook,
            require_root_owned=self.require_root_owned,
        )

    def record_matches(self, detail, *, rolled_back=False):
        current = self._current()
        if rolled_back:
            return (
                current.database_url == detail["old_database_url"]
                and current.generation > detail["new_generation"]
            )
        return current == PointerRecord(
            detail["new_database_url"], detail["new_generation"]
        )

    def rollback(self, detail):
        current = self._current()
        expected = PointerRecord(
            detail["new_database_url"], detail["new_generation"]
        )
        if current != expected:
            raise CompoundRestoreRefused(
                "The file pointer changed before compound rollback."
            )
        write_pointer_atomic(
            self.path,
            PointerRecord(detail["old_database_url"], current.generation + 1),
            expected_generation=current.generation,
            invalidate=self.invalidate_capabilities,
            crash_hook=self.crash_hook,
            require_root_owned=self.require_root_owned,
        )


class ExternalCompoundPointer:
    def __init__(
        self, *, store, topology, expected_version, current_identity,
        runtime_url, invalidate_capabilities,
    ):
        self.store = store
        self.topology = topology
        self.expected_version = expected_version
        self.current_identity = current_identity
        self.runtime_url = runtime_url
        self.invalidate_capabilities = invalidate_capabilities

    def preflight(self, *, allow_committed_cutover=False):
        if getattr(self.store, "supports_compare_and_swap", False) is not True:
            raise CompoundRestoreRefused(
                "The external DATABASE_URL control plane lacks native CAS."
            )
        current = self.store.read()
        if (
            current.store_version != self.expected_version
            and not allow_committed_cutover
        ):
            raise CompoundRestoreRefused(
                "The external pointer expected version is stale."
            )
        if not isinstance(self.topology, CompoundTopologyFacts) or (
            self.topology.authoritative_database_url != "external"
            or self.topology.external_journalled_swap is not True
        ):
            raise CompoundRestoreRefused(
                "The external DATABASE_URL has no journalled control-plane swap."
            )
        if not _queried_identity(self.current_identity()):
            raise CompoundRestoreRefused(
                "The external path could not query the live database identity."
            )
        return self.topology

    def current_generation(self):
        return self.store.read().record.generation

    def cutover_detail(self, sibling):
        current = self.store.read()
        return {
            "old_store_version": current.store_version,
            "old_database_url": current.record.database_url,
            "new_database_url": self.runtime_url(sibling),
            "old_generation": current.record.generation,
            "new_generation": current.record.generation + 1,
            "new_database_identity": list(sibling.identity.durable_key()),
        }

    def compare_and_swap(self, detail):
        result = compare_and_swap_external(
            self.store,
            expected_version=detail["old_store_version"],
            record=PointerRecord(
                detail["new_database_url"], detail["new_generation"]
            ),
            invalidate=self.invalidate_capabilities,
        )
        self.expected_version = result.store_version

    def record_matches(self, detail, *, rolled_back=False):
        current = self.store.read().record
        if rolled_back:
            return (
                current.database_url == detail["old_database_url"]
                and current.generation > detail["new_generation"]
            )
        return current == PointerRecord(
            detail["new_database_url"], detail["new_generation"]
        )

    def rollback(self, detail):
        current = self.store.read()
        if current.record != PointerRecord(
            detail["new_database_url"], detail["new_generation"]
        ):
            raise CompoundRestoreRefused(
                "The external pointer changed before compound rollback."
            )
        result = compare_and_swap_external(
            self.store,
            expected_version=current.store_version,
            record=PointerRecord(
                detail["old_database_url"], current.record.generation + 1
            ),
            invalidate=self.invalidate_capabilities,
        )
        self.expected_version = result.store_version


def _queried_identity(identity):
    return (
        isinstance(identity, ResourceIdentity)
        and bool(identity.endpoint)
        and bool(identity.database_name)
        and bool(identity.database_uuid)
        and type(identity.database_oid) is int
        and identity.database_oid > 0
    )
