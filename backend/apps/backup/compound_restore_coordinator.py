"""Lane E target compound restore, ordered entirely by the H1 supervisor."""

from dataclasses import replace

from apps.backup.host_marker import (
    MarkerState,
    OperationIdentity,
)
from apps.backup.host_supervisor import supervise_run

from .compound_restore_cutover import journalled_cutover
from .compound_restore_capability import arm_candidate_capability
from .compound_restore_ledger import done_detail, effect, incomplete
from .compound_restore_objects import restore_objects, validate_object_effects
from .compound_restore_preflight import validate_compound_preflight
from .compound_restore_types import (
    CompoundRestoreRefused,
    require_complete_live_identity,
)


PHASES = (
    "static-preflight",
    "persist-offline",
    "exclude-writers",
    "sibling-allocation",
    "database-restore",
    "roles-and-grants",
    "rehydrate-not-restored-and-reservations",
    "install-fences",
    "verify-catalog-and-enforcement",
    "restore-main-objects",
    "prepare-quarantine-readiness",
    "candidate-health-marker",
    "arm-candidate-capability",
    "start-candidate-backend",
    "verify-quarantine",
    "cutover",
    "quarantine-marker-and-grants",
    "recovery-acknowledgement",
    "normal-marker",
    "start-normal-writers",
    "finalize",
)


def run_compound_restore(
    *, ops_dir, inputs, artifact, database, writers, pointer, target,
    object_store, capability, capability_journal, marker_writer,
    require_root_owned=True,
):
    """Run/resume the target coordinator; no mutation precedes static admission."""

    with supervise_run(
        ops_dir,
        run_id=inputs.run_id,
        artifact_sha256=inputs.artifact_sha256,
        phases=PHASES,
        require_root_owned=require_root_owned,
    ) as session:
        ledger = session.ledger
        preflight, topology, capability_facts = validate_compound_preflight(
            inputs, pointer=pointer, database=database, capability=capability,
            allow_committed_cutover=(
                done_detail(ledger, "cutover") is not None
                or incomplete(ledger, "cutover") is not None
            ),
        )
        manifest = preflight.manifest
        static_detail = effect(
            ledger, "static-preflight", {"mutation": False},
            lambda _prior: {
                "mutation": False,
                "path": topology.path,
                "capability": capability_facts,
                "pointer_generation": pointer.current_generation(),
            },
        )
        effect(
            ledger, "persist-offline", {"fsynced": False},
            lambda _prior: writers.persist_offline(inputs, topology),
        )
        effect(
            ledger, "exclude-writers", {"writers": list(topology.writer_set)},
            lambda _prior: writers.exclude(topology.writer_set),
        )
        if not writers.prove_excluded(topology.writer_set):
            raise CompoundRestoreRefused(
                f"The {topology.path} path did not exclude its complete writer set."
            )

        operation = OperationIdentity(
            inputs.run_id,
            inputs.artifact_sha256,
            inputs.capture_id,
            static_detail["pointer_generation"],
        )
        sibling = _prepare_sibling(
            ledger, database=database, marker_writer=marker_writer,
            operation=operation,
        )
        sibling = _restore_database(
            ledger, database=database, artifact=artifact, sibling=sibling,
            marker_writer=marker_writer, operation=operation,
        )
        grants = effect(
            ledger, "roles-and-grants", {"state": "not-applied"},
            lambda _prior: database.apply_runtime_ownership_and_grants(sibling),
        )
        rehydrated = effect(
            ledger,
            "rehydrate-not-restored-and-reservations",
            {"installed": False},
            lambda _prior: target.rehydrate(sibling, inputs, manifest),
        )
        sibling = replace(
            sibling,
            identity=require_complete_live_identity(
                database.query_identity(sibling)
            ),
        )
        enforcement = effect(
            ledger, "install-fences", {"installed": False},
            lambda _prior: target.install_enforcement(sibling, inputs, manifest),
        )
        catalog = effect(
            ledger, "verify-catalog-and-enforcement", {"verified": False},
            lambda _prior: target.verify_catalog(sibling, inputs, manifest),
        )
        object_plan = tuple(object_store.plan_main(artifact, manifest))
        validate_object_effects(object_plan)
        object_detail = effect(
            ledger, "restore-main-objects", {"effects": list(object_plan)},
            lambda prior: restore_objects(
                object_store, artifact, manifest,
                tuple((prior or {"detail": {"effects": object_plan}})[
                    "detail"
                ]["effects"]),
            ),
        )
        quarantine_plan = effect(
            ledger, "prepare-quarantine-readiness", {"prepared": False},
            lambda _prior: target.prepare_quarantine(sibling, inputs, manifest),
        )
        readiness = quarantine_plan.get("marker_readiness")
        if not isinstance(readiness, dict):
            raise CompoundRestoreRefused(
                "Candidate quarantine did not produce marker readiness declarations."
            )
        marker_database = database.marker_identity(sibling)
        effect(
            ledger, "candidate-health-marker", {"state": "candidate-health"},
            lambda _prior: marker_writer.transition_bound(
                MarkerState.CANDIDATE_HEALTH,
                marker_database,
                operation,
                readiness=readiness,
            ),
        )
        def arm_capability(prior):
            if prior is not None:
                capability_journal.invalidate_all(
                    "compound-capability-arm-interrupted"
                )
            return arm_candidate_capability(
                capability_journal, marker_writer, database, sibling
            )

        effect(
            ledger, "arm-candidate-capability", {"state": "not-armed"},
            arm_capability,
        )
        def start_candidate(prior):
            if prior is not None:
                arm_candidate_capability(
                    capability_journal, marker_writer, database, sibling,
                    interrupted=True,
                )
            return writers.start_candidate_backend(sibling, migrate=False)

        effect(
            ledger, "start-candidate-backend", {"migrate": False},
            start_candidate,
        )
        quarantine = effect(
            ledger, "verify-quarantine", {"verified": False},
            lambda _prior: target.verify_quarantine(sibling, inputs, manifest),
        )
        if quarantine.get("verified") is not True:
            raise CompoundRestoreRefused("The quarantined candidate readiness probe failed.")
        cutover = journalled_cutover(
            ledger, pointer, database, sibling,
            ownership_proof=_ownership_proof(sibling),
            grant_state=grants,
            object_effects=tuple(object_detail["effects"]),
        )

        def quarantine_after_cutover(_prior):
            marker = marker_writer.transition_bound(
                MarkerState.QUARANTINED_AFTER_CUTOVER,
                marker_database,
                operation,
                readiness=readiness,
            )
            writable = database.apply_grant_state(
                sibling, MarkerState.QUARANTINED_AFTER_CUTOVER.value
            )
            return {"marker": marker, "grant_state": writable}

        effect(
            ledger, "quarantine-marker-and-grants",
            {"state": "quarantined-after-cutover"}, quarantine_after_cutover,
        )
        acknowledgement = effect(
            ledger, "recovery-acknowledgement", {"acknowledged": False},
            lambda _prior: target.acknowledge_recovery(sibling, inputs),
        )
        if acknowledgement.get("acknowledged") is not True:
            raise CompoundRestoreRefused("Explicit recovery acknowledgement is absent.")
        effect(
            ledger, "normal-marker", {"acknowledged": True},
            lambda _prior: marker_writer.transition_bound(
                MarkerState.NORMAL, marker_database, operation, readiness=readiness
            ),
        )
        effect(
            ledger, "start-normal-writers", {"writers": list(topology.writer_set)},
            lambda _prior: writers.start_normal(sibling, topology.writer_set),
        )

        def finalize(_prior):
            session.terminal(capability_journal, reason="compound-restore-finalized")
            return {
                "complete": True,
                "lock_still_held": not session.lock_handle.closed,
                "new_generation": cutover["new_generation"],
                "rehydrated": rehydrated,
                "enforcement": enforcement,
                "catalog": catalog,
            }

        effect(ledger, "finalize", {"complete": False}, finalize)
        return {
            "run_id": inputs.run_id,
            "new_generation": cutover["new_generation"],
        }


def _prepare_sibling(ledger, *, database, marker_writer, operation):
    allocation = done_detail(ledger, "sibling-allocation")
    if allocation is not None:
        return database.recover_sibling(allocation["sibling"])
    prior = incomplete(ledger, "sibling-allocation")
    begun = prior or ledger.begin(
        "sibling-allocation", {"planned": True, "marker_bound": False}
    )
    marker_writer.write_intent(operation)
    sibling = database.allocate(fresh_after_interrupted_restore=prior is not None)
    sibling = database.prove_sibling(sibling)
    # This is the adapter's live query result, not a pointer/Compose assertion.
    marker_database = database.marker_identity(sibling)
    marker_writer.bind_database(marker_database, operation)
    detail = {"sibling": _ownership_proof(sibling), "marker_bound": True}
    ledger.finish(begun, detail)
    return sibling


def _restore_database(
    ledger, *, database, artifact, sibling, marker_writer, operation
):
    completed = done_detail(ledger, "database-restore")
    if completed is not None:
        return database.recover_sibling(completed["sibling"])
    prior = incomplete(ledger, "database-restore")
    if prior is not None:
        marker_writer.write_intent(operation)
        sibling = database.allocate(fresh_after_interrupted_restore=True)
        sibling = database.prove_sibling(sibling)
        marker_writer.bind_database(database.marker_identity(sibling), operation)
    detail = {"sibling": _ownership_proof(sibling), "empty": sibling.empty}
    begun = ledger.begin("database-restore", detail)
    database.restore(sibling, artifact.database_dump_path())
    ledger.finish(begun, detail)
    return sibling


def _ownership_proof(sibling):
    return {
        "identity": list(sibling.identity.durable_key()),
        "created_by_this_run": sibling.created_by_this_run,
        "owner_marker": sibling.owner_marker,
        "empty": sibling.empty,
        "non_routable": sibling.non_routable,
    }
