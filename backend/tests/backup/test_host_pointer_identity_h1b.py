from dataclasses import dataclass
import uuid

import pytest

from apps.backup.database_identity import DatabaseIdentityError, query_live_database_identity
from apps.backup.host_pointer import (
    PointerError,
    PointerRecord,
    VersionedPointer,
    compare_and_swap_external,
    read_pointer,
    write_pointer_atomic,
)
from apps.backup.host_topology_record import (
    TopologyRecordError,
    configuration_facts,
    validate_compose_wrapper,
    write_topology_record,
)


def test_atomic_pointer_crash_boundaries_preserve_a_complete_record(tmp_path):
    initial = PointerRecord("postgres://app@db/active", 1)
    updated = PointerRecord("postgres://app@db/candidate", 2)

    for stage, expected in (
        ("before_replace", initial),
        ("after_replace", updated),
        ("before_parent_fsync", updated),
        ("after_parent_fsync", updated),
    ):
        path = tmp_path / f"database-pointer-{stage}.env"
        write_pointer_atomic(path, initial, require_root_owned=False)

        def crash(observed):
            if observed == stage:
                raise RuntimeError("simulated crash")

        with pytest.raises(RuntimeError, match="simulated crash"):
            write_pointer_atomic(
                path,
                updated,
                expected_generation=1,
                invalidate=lambda _reason: None,
                crash_hook=crash,
                require_root_owned=False,
            )
        assert read_pointer(path, require_root_owned=False) == expected


@dataclass
class _Store:
    value: VersionedPointer
    supports_compare_and_swap: bool = True

    def read(self):
        return self.value

    def compare_and_swap(self, expected_version, record):
        if self.value.store_version != expected_version:
            raise PointerError("stale in store")
        self.value = VersionedPointer(record, "version-2")
        return self.value


def test_external_pointer_cas_refuses_a_stale_expected_version():
    store = _Store(VersionedPointer(PointerRecord("postgres://old", 7), "version-1"))

    with pytest.raises(PointerError, match="stale"):
        compare_and_swap_external(
            store,
            expected_version="version-0",
            record=PointerRecord("postgres://new", 8),
            invalidate=lambda _reason: None,
        )


def test_wrapper_refuses_duplicate_pointer_fields_and_digest_drift(tmp_path):
    static = tmp_path / "static.env"
    compose = tmp_path / "compose.yml"
    pointer = tmp_path / "database-pointer.env"
    record = tmp_path / "topology.json"
    static.write_text("SPACEWORKS_SCHEDULER_MODE=image\n", encoding="utf-8")
    compose.write_text("services: {}\n", encoding="utf-8")
    write_pointer_atomic(
        pointer,
        PointerRecord("postgres://app@db/active", 1),
        require_root_owned=False,
    )
    facts = configuration_facts(
        topology="bundled", static_env=static, compose_files=[compose]
    )
    write_topology_record(record, facts)
    assert validate_compose_wrapper(
        topology="bundled",
        static_env=static,
        pointer_file=pointer,
        topology_record=record,
        compose_files=[compose],
        require_root_owned=False,
    )["scheduler_mode"] == "image"

    static.write_text(
        "SPACEWORKS_SCHEDULER_MODE=image\nDATABASE_URL=postgres://wrong\n",
        encoding="utf-8",
    )
    with pytest.raises(TopologyRecordError, match="duplicates"):
        validate_compose_wrapper(
            topology="bundled",
            static_env=static,
            pointer_file=pointer,
            topology_record=record,
            compose_files=[compose],
            require_root_owned=False,
        )
    static.write_text("SPACEWORKS_SCHEDULER_MODE=image\n", encoding="utf-8")
    compose.write_text("services: {changed: {}}\n", encoding="utf-8")
    with pytest.raises(TopologyRecordError, match="digest drifted"):
        validate_compose_wrapper(
            topology="bundled",
            static_env=static,
            pointer_file=pointer,
            topology_record=record,
            compose_files=[compose],
            require_root_owned=False,
        )


def test_pointer_reader_refuses_group_writable_or_untrusted_state(tmp_path):
    pointer = tmp_path / "database-pointer.env"
    pointer.write_text(
        "DATABASE_URL=postgres://app@db/active\n"
        "SPACEWORKS_DB_POINTER_GENERATION=1\n",
        encoding="utf-8",
    )
    pointer.chmod(0o666)

    with pytest.raises(PointerError, match="misowned"):
        read_pointer(pointer, require_root_owned=True)


def test_wrapper_refuses_an_undeclared_scheduler_mode(tmp_path):
    static = tmp_path / "static.env"
    compose = tmp_path / "compose.yml"
    static.write_text("STATIC_ONLY=yes\n", encoding="utf-8")
    compose.write_text("services: {}\n", encoding="utf-8")

    with pytest.raises(TopologyRecordError, match="scheduler mode"):
        configuration_facts(
            topology="bundled", static_env=static, compose_files=[compose]
        )


class _Cursor:
    def __init__(self, *, database_uuid):
        self.database_uuid = database_uuid
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _params=None):
        self.query = " ".join(query.split())
        if "pg_control_system" in self.query:
            raise PermissionError("managed provider denies pg_control_system")

    def fetchone(self):
        if "FROM pg_database" in self.query:
            return ("candidate", 8421)
        if "to_regclass" in self.query:
            return ("backup_deploymentdatabaseidentity",)
        if "database_uuid::text" in self.query:
            return (
                self.database_uuid,
                str(uuid.UUID(int=2)),
                "a" * 64,
                str(uuid.UUID(int=3)),
            )
        raise AssertionError(self.query)


class _Connection:
    autocommit = False

    def __init__(self, database_uuid):
        self.database_uuid = database_uuid

    def get_dsn_parameters(self):
        return {
            "host": "managed.example",
            "port": "5432",
            "dbname": "pointer-name-is-not-authority",
            "sslmode": "require",
        }

    def cursor(self):
        return _Cursor(database_uuid=self.database_uuid)


def test_identity_is_endpoint_plus_queried_uuid_with_pg_control_fallback():
    database_uuid = str(uuid.uuid4())
    identity = query_live_database_identity(_Connection(database_uuid))

    assert identity.endpoint.host == "managed.example"
    assert identity.endpoint.database == "candidate"
    assert identity.database_uuid == database_uuid
    assert identity.system_identifier is None
    assert identity.endpoint.database != "pointer-name-is-not-authority"


class _PointerOnlyCursor(_Cursor):
    def fetchone(self):
        if "to_regclass" in self.query:
            return (None,)
        return super().fetchone()


class _PointerOnlyConnection(_Connection):
    def cursor(self):
        return _PointerOnlyCursor(database_uuid=self.database_uuid)


def test_pointer_name_without_queried_uuid_is_not_an_identity():
    with pytest.raises(DatabaseIdentityError, match="singleton is unavailable"):
        query_live_database_identity(_PointerOnlyConnection(str(uuid.uuid4())))
