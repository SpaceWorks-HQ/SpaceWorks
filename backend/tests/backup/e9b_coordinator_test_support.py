from dataclasses import replace
from types import SimpleNamespace
import uuid

from apps.backup.compound_restore_types import CompoundRestoreInputs, CompoundTopologyFacts
from apps.backup.host_marker import DatabaseIdentity
from apps.backup.host_supervisor import HostMarkerTransition
from apps.tenant_migration.tenant_restore_types import ResourceIdentity, SiblingResource

ARTIFACT = "a" * 64
CAPTURE = str(uuid.uuid4())
RUN = str(uuid.uuid4())

def inputs():
    return CompoundRestoreInputs(
        RUN, CAPTURE, ARTIFACT, "/outer.age", "/outer.tar",
        "/manifest.json", "/keys.json", ARTIFACT,
    )

class Journal:
    def __init__(self, events):
        self.events, self.armed = events, None
    def arm(self, record):
        self.events.append("capability-armed")
        self.armed = record
        return record
    def invalidate_all(self, reason):
        self.events.append(f"invalidate:{reason}")
        self.armed = None
        return 1

class MarkerWriter(HostMarkerTransition):
    def __init__(self, path, journal, events):
        super().__init__(path, journal, require_root_owned=False)
        self.events = events
    def transition_bound(self, state, *args, **kwargs):
        self.events.append(f"marker:{state.value}")
        return super().transition_bound(state, *args, **kwargs)

class Database:
    def __init__(self, events):
        self.events, self.serial, self.sibling, self.owned = events, 0, None, True
    def preflight(self, *, allow_committed_cutover=False):
        return {
            "privileges_probed": True, "can_restore": True,
            "can_apply_grants": True, "can_exclude_sessions": True,
            "empty_sibling": True, "non_routable_sibling": True,
        }
    def allocate(self, *, fresh_after_interrupted_restore):
        if self.sibling is None or fresh_after_interrupted_restore:
            self.serial += 1
            identity = ResourceIdentity(
                "db:5432", f"candidate_{self.serial}", str(uuid.uuid4()),
                100 + self.serial,
            )
            self.sibling = SiblingResource(
                identity, f"postgres://owner@db/{identity.database_name}",
                False, True, True, f"owner-proof-{self.serial}",
            )
        self.events.append(f"allocate:{self.serial}")
        return self.sibling
    def prove_sibling(self, sibling):
        return replace(sibling, empty=True)
    def recover_sibling(self, _proof):
        return replace(self.sibling, empty=True)
    def restore(self, _sibling, _path):
        self.events.append("database-restore")
    def apply_runtime_ownership_and_grants(self, _sibling):
        self.events.append("roles-grants")
        return {"state": "candidate-preparation", "runtime": "read-only"}
    def apply_grant_state(self, _sibling, state):
        self.events.append(f"grants:{state}")
        return {"state": state, "runtime": "writable"}
    def query_identity(self, sibling):
        self.events.append("identity-query")
        return sibling.identity
    def marker_identity(self, sibling):
        self.events.append("identity-query-for-marker")
        identity = sibling.identity
        return DatabaseIdentity(identity.database_name, identity.database_oid, {
            "endpoint": {
                "host": "db", "port": 5432,
                "database": identity.database_name, "tls_identity": "",
            },
            "database_uuid": identity.database_uuid,
            "system_identifier": None,
        })
    def owns(self, _sibling, _proof):
        return self.owned

class Pointer:
    def __init__(self, events, crash=None):
        self.events, self.current, self.crash = events, "old", crash
    def preflight(self):
        return CompoundTopologyFacts(
            "bundled-compose", True, True, True, True, True,
            ("backend", "worker", "beat"),
        )
    def current_generation(self):
        return 1 if self.current == "old" else 2
    def cutover_detail(self, sibling):
        return {
            "old_database_url": "postgres://app@db/active",
            "new_database_url": "postgres://app@db/candidate",
            "old_generation": 1, "new_generation": 2,
            "new_database_identity": list(sibling.identity.durable_key()),
        }
    def compare_and_swap(self, _detail):
        self.events.append("pointer-cutover")
        if self.crash == "before":
            self.crash = None
            raise RuntimeError("crash before pointer")
        self.current = "new"
        if self.crash == "after":
            self.crash = None
            raise RuntimeError("crash after pointer")
    def record_matches(self, _detail, *, rolled_back=False):
        return self.current == ("old" if rolled_back else "new")
    def rollback(self, _detail):
        self.events.append("pointer-rollback")
        if self.crash == "rollback-before":
            self.crash = None
            raise RuntimeError("crash before rollback pointer")
        self.current = "old"
        if self.crash == "rollback-after":
            self.crash = None
            raise RuntimeError("crash after rollback pointer")

class Writers:
    def __init__(self, events):
        self.events, self.excluded = events, False
    def persist_offline(self, _inputs, _topology):
        self.events.append("offline")
        return {"fsynced": True}
    def exclude(self, _writers):
        self.events.append("exclude")
        self.excluded = True
        return {"excluded": True}
    def prove_excluded(self, _writers):
        return self.excluded
    def start_candidate_backend(self, _sibling, *, migrate):
        assert migrate is False
        self.events.append("candidate-backend-without-migrate")
        return {"started": "backend", "migrate": migrate}
    def start_normal(self, _sibling, writers):
        self.events.append("start:" + ",".join(writers))
        return {"writers": list(writers)}

class Target:
    def __init__(self, events):
        self.events = events
    def rehydrate(self, *_args):
        self.events.append("not-restored-and-reservations")
        return {"not_restored": 1, "reservations": 2}
    def install_enforcement(self, *_args):
        self.events.append("fences-installed")
        return {"fences": 1}
    def verify_catalog(self, *_args):
        self.events.append("catalog-verified")
        return {"verified": True}
    def prepare_quarantine(self, *_args):
        return {"marker_readiness": {
            "reservations": [], "fences": [], "not_restored": [],
        }}
    def verify_quarantine(self, *_args):
        self.events.append("candidate-readiness")
        return {"verified": True}
    def acknowledge_recovery(self, *_args):
        self.events.append("acknowledgement")
        return {"acknowledged": True, "actor": "recovery-operator"}

class Objects:
    def __init__(self, events):
        self.events = events
    def plan_main(self, _artifact, _manifest):
        return (
            {"bucket": "private", "key": "main/x", "digest": "d" * 64,
             "outcome": "created_by_this_run"},
            {"bucket": "private", "key": "main/existing", "digest": "e" * 64,
             "outcome": "accepted_existing"},
        )
    def restore_main(self, _artifact, _manifest, effects):
        self.events.append("object-write")
        return effects
    def rollback(self, effects):
        self.events.append("object-rollback")
        return tuple({**item, "reversed": True} for item in effects)

class Artifact:
    def database_dump_path(self):
        return "/bundle/database.dump"

class Capability:
    def validate(self, **_kwargs):
        return {"validated": True, "record_sha256": "c" * 64}

def invoke(monkeypatch, tmp_path, *, crash=None):
    events = []
    database = Database(events)
    pointer = Pointer(events, crash=crash)
    journal = Journal(events)
    marker = MarkerWriter(tmp_path / "marker.json", journal, events)
    monkeypatch.setattr(
        "apps.backup.compound_restore_coordinator.validate_compound_preflight",
        lambda *_args, **_kwargs: (
            SimpleNamespace(manifest={"capture_id": CAPTURE}),
            pointer.preflight(), {"validated": True},
        ),
    )
    arguments = dict(
        ops_dir=tmp_path / "ops", inputs=inputs(), artifact=Artifact(),
        database=database, writers=Writers(events), pointer=pointer,
        target=Target(events), object_store=Objects(events),
        capability=Capability(), capability_journal=journal,
        marker_writer=marker, require_root_owned=False,
    )
    return arguments, events, pointer, database
