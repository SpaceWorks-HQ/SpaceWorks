"""D7 binding around H1's one-record pointer CAS primitives."""

from dataclasses import asdict

from apps.backup.host_pointer import (
    PointerRecord,
    compare_and_swap_external,
    read_pointer,
    write_pointer_atomic,
)

from .tenant_restore_types import TenantRestoreRefused, TopologyPreflight


class FilePointerAdapter:
    def __init__(
        self, *, path, current_identity, marker_reader, runtime_url,
        invalidate_capabilities, scheduler_mode, complete_writer_set,
        static_config_initialized=True, cloud_config_digest_matches=True,
        require_root_owned=True, crash_hook=None,
    ):
        self.path = path
        self._current_identity = current_identity
        self.marker_reader = marker_reader
        self.runtime_url = runtime_url
        self.invalidate_capabilities = invalidate_capabilities
        self.scheduler_mode = scheduler_mode
        self.complete_writer_set = tuple(complete_writer_set)
        self.static_config_initialized = static_config_initialized
        self.cloud_config_digest_matches = cloud_config_digest_matches
        self.require_root_owned = require_root_owned
        self.crash_hook = crash_hook

    def _current(self):
        return read_pointer(self.path, require_root_owned=self.require_root_owned)

    def preflight(self, *, allow_committed_cutover=False):
        self._current()
        identity = self._current_identity()
        return TopologyPreflight(
            adapter_supported=True,
            pointer_compare_and_swap=True,
            exact_current_identity=identity,
            scheduler_mode=self.scheduler_mode,
            cloud_config_digest_matches=self.cloud_config_digest_matches,
            static_config_initialized=self.static_config_initialized,
            complete_writer_set=self.complete_writer_set,
        )

    def current_generation(self):
        return self._current().generation

    def cutover_detail(self, sibling):
        current = self._current()
        marker = self.marker_reader(sibling)
        return {
            "old_database_url": current.database_url,
            "old_generation": current.generation,
            "old_database_identity": asdict(self._current_identity()),
            "new_database_url": self.runtime_url(sibling),
            "new_generation": current.generation + 1,
            "new_database_marker": marker,
        }

    def compare_and_swap(self, detail):
        write_pointer_atomic(
            self.path,
            PointerRecord(detail["new_database_url"], detail["new_generation"]),
            expected_generation=detail["old_generation"],
            invalidate=self.invalidate_capabilities,
            crash_hook=self.crash_hook,
            require_root_owned=self.require_root_owned,
        )

    def record_matches(self, detail):
        current = self._current()
        return current == PointerRecord(
            detail["new_database_url"], detail["new_generation"]
        )


class ExternalPointerAdapter:
    def __init__(
        self, *, store, expected_version, current_identity, marker_reader,
        runtime_url, invalidate_capabilities, scheduler_mode, complete_writer_set,
    ):
        self.store = store
        self.expected_version = expected_version
        self._current_identity = current_identity
        self.marker_reader = marker_reader
        self.runtime_url = runtime_url
        self.invalidate_capabilities = invalidate_capabilities
        self.scheduler_mode = scheduler_mode
        self.complete_writer_set = tuple(complete_writer_set)

    def preflight(self, *, allow_committed_cutover=False):
        current = self.store.read()
        if current.store_version != self.expected_version and not allow_committed_cutover:
            raise TenantRestoreRefused(
                "External pointer expected version is stale."
            )
        return TopologyPreflight(
            adapter_supported=True,
            pointer_compare_and_swap=bool(
                getattr(self.store, "supports_compare_and_swap", False)
            ),
            exact_current_identity=self._current_identity(),
            scheduler_mode=self.scheduler_mode,
            complete_writer_set=self.complete_writer_set,
        )

    def current_generation(self):
        return self.store.read().record.generation

    def cutover_detail(self, sibling):
        current = self.store.read()
        return {
            "old_store_version": current.store_version,
            "old_database_url": current.record.database_url,
            "old_generation": current.record.generation,
            "old_database_identity": asdict(self._current_identity()),
            "new_database_url": self.runtime_url(sibling),
            "new_generation": current.record.generation + 1,
            "new_database_marker": self.marker_reader(sibling),
        }

    def compare_and_swap(self, detail):
        compare_and_swap_external(
            self.store,
            expected_version=detail["old_store_version"],
            record=PointerRecord(detail["new_database_url"], detail["new_generation"]),
            invalidate=self.invalidate_capabilities,
        )

    def record_matches(self, detail):
        return self.store.read().record == PointerRecord(
            detail["new_database_url"], detail["new_generation"]
        )
