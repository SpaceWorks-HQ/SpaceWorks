"""The exact D7 §5.4 host-supervised ordering spine."""

from __future__ import annotations

from dataclasses import asdict

from apps.backup.host_marker import OperationIdentity
from apps.backup.host_supervisor import supervise_run

from .tenant_restore_activation import cutover as _cutover, start_serving
from .tenant_restore_objects import (
    load_object,
    object_phase,
    validate_object_plan,
)
from .tenant_restore_phases import ordered_phases
from .tenant_restore_ledger import (
    done_detail as _done_detail,
    incomplete_effect as _incomplete,
    ledger_effect as _effect,
    phase_done as _done,
    sibling_detail as _sibling_detail,
)
from .tenant_restore_preflight import validate_static_preflight
from .tenant_restore_scheduler import assert_same_fence_receipt, receipt_from_detail
from .tenant_restore_sibling import prepare_bound_sibling
from .tenant_restore_types import (
    StaticPreflight,
    TenantRestoreRefused,
)


def _static_preflight(inputs, artifact, database, pointer, *, scheduler, ledger):
    cutover_started = _done(ledger, "activation-cutover") or (
        _incomplete(ledger, "activation-cutover") is not None
    )
    topology = pointer.preflight(allow_committed_cutover=cutover_started)
    facts = validate_static_preflight(StaticPreflight(
        artifact=artifact.static_preflight(inputs),
        topology=topology,
        privileges=database.privilege_facts(),
        sibling=database.sibling_plan(),
        source_identity=database.source_identity(),
        scratch_identity=(
            database.scratch_identity()
            if hasattr(database, "scratch_identity") else None
        ),
    ), allow_committed_sibling=cutover_started)
    if (facts.topology.scheduler_mode == "external") != (scheduler is not None):
        raise TenantRestoreRefused(
            "External scheduler topology and callback adapter declaration disagree."
        )
    return facts


def _reestablish_exclusion(ledger, inputs, preflight, writers, scheduler):
    if not writers.prove_image_writers_excluded(preflight.topology.complete_writer_set):
        writers.exclude_image_writers(preflight.topology.complete_writer_set)
    if not writers.prove_image_writers_excluded(preflight.topology.complete_writer_set):
        raise TenantRestoreRefused("The complete image writer set is not excluded.")
    if scheduler is not None and not _done(ledger, "activation-cutover"):
        expected = receipt_from_detail(_done_detail(ledger, "external-scheduler-fence"))
        actual = scheduler.status(run_id=inputs.run_id)
        assert_same_fence_receipt(expected, actual)


def run_target_restore(
    *, ops_dir, inputs, artifact, database, writers, pointer, target,
    object_store, destination_prefix, capability_journal, marker_writer,
    storage_makerspace=None, scheduler=None,
    require_root_owned=True,
):
    """Run or resume Phase T; the H1 supervisor retains the lock until return."""
    phases = ordered_phases(inputs, external_scheduler=scheduler is not None)
    with supervise_run(
        ops_dir,
        run_id=inputs.run_id,
        artifact_sha256=inputs.artifact_sha256,
        phases=phases,
        require_root_owned=require_root_owned,
    ) as session:
        ledger = session.ledger
        # Static facts are re-probed on every invocation. The first successful probe is
        # also ledgered; a resume never trusts that historical probe as current truth.
        preflight = _static_preflight(
            inputs, artifact, database, pointer, scheduler=scheduler, ledger=ledger
        )
        _effect(
            ledger, "static-preflight", {"target_state_created": False},
            lambda: {"validated": True, "target_state_created": False},
        )
        if _done(ledger, "sibling-allocation"):
            _reestablish_exclusion(ledger, inputs, preflight, writers, scheduler)

        _effect(
            ledger, "persist-offline", {"fsynced": False},
            lambda: writers.persist_offline(inputs, preflight),
        )
        _effect(
            ledger, "exclude-image-writers", {"writers": list(preflight.topology.complete_writer_set)},
            lambda: writers.exclude_image_writers(preflight.topology.complete_writer_set),
        )
        if not writers.prove_image_writers_excluded(preflight.topology.complete_writer_set):
            raise TenantRestoreRefused("The complete image writer set is not excluded.")

        if scheduler is not None:
            old = asdict(preflight.topology.exact_current_identity)
            stop = _effect(
                ledger, "external-scheduler-stop", {"old_identity": old},
                lambda: scheduler.stop(
                    run_id=inputs.run_id,
                    old_identity=old,
                    old_generation=pointer.current_generation(),
                ),
            )
            receipt = _effect(
                ledger, "external-scheduler-fence",
                {"expected_scheduler_generation": stop["pre_stop_generation"]},
                lambda: asdict(scheduler.fence(
                    run_id=inputs.run_id,
                    expected_scheduler_generation=stop["pre_stop_generation"],
                )),
            )
            assert_same_fence_receipt(
                receipt_from_detail(receipt), scheduler.status(run_id=inputs.run_id)
            )

        sibling_box = {}
        prior_allocation = _incomplete(ledger, "sibling-allocation")
        planned_identity = preflight.sibling.planned_identity
        planned_detail = asdict(planned_identity) if planned_identity else None
        operation = OperationIdentity(
            inputs.run_id, inputs.artifact_sha256, inputs.capture_id,
            pointer.current_generation(),
        )

        def allocate():
            require_fresh = prior_allocation is not None

            def after_intent():
                nonlocal require_fresh
                if require_fresh and preflight.sibling.supplied:
                    prior_identity = prior_allocation["detail"].get("planned_identity")
                    if planned_detail is None or planned_detail == prior_identity:
                        raise TenantRestoreRefused(
                            "Interrupted allocation requires a new empty operator-supplied sibling."
                        )
                    require_fresh = False

            sibling = prepare_bound_sibling(
                database, marker_writer, operation,
                fresh_after_interrupted_restore=require_fresh, after_intent=after_intent,
            )
            sibling_box["value"] = sibling
            return {
                "sibling": _sibling_detail(sibling),
                "writers_excluded": True,
                "marker_bound": True,
            }
        allocation_detail = _effect(
            ledger, "sibling-allocation",
            {
                "planned": preflight.sibling.planned_name,
                "planned_identity": planned_detail,
            },
            allocate,
        )
        prior_restore = _incomplete(ledger, "database-restore")
        supplied_fresh = False
        sibling = sibling_box.get("value")
        if sibling is None:
            if prior_restore is not None and preflight.sibling.supplied:

                def validate_supplied(candidate):
                    prior_identity = prior_restore["detail"].get("sibling", {}).get("identity")
                    if prior_identity == repr(candidate.identity.durable_key()):
                        database.cleanup(candidate, successful=False)
                        raise TenantRestoreRefused(
                            "Interrupted restore requires a fresh operator-supplied sibling."
                        )

                sibling = prepare_bound_sibling(
                    database, marker_writer, operation,
                    fresh_after_interrupted_restore=False,
                    validate_allocated=validate_supplied,
                )
                supplied_fresh = True
            else:
                sibling = database.recover_sibling(allocation_detail["sibling"])

        interrupted = session.resume.requires_new_empty_sibling or prior_restore is not None
        if interrupted:
            if sibling.created_by_this_run:
                sibling = prepare_bound_sibling(
                    database, marker_writer, operation,
                    fresh_after_interrupted_restore=True,
                    after_intent=lambda: database.cleanup(sibling, successful=False),
                )
            elif not supplied_fresh and (
                prior_restore is not None
                and prior_restore["detail"].get("sibling", {}).get("identity")
                == repr(sibling.identity.durable_key())
            ):
                database.cleanup(sibling, successful=False)
                raise TenantRestoreRefused(
                    "Interrupted restore requires a fresh operator-supplied sibling."
                )
        if not _done(ledger, "database-restore"):
            restore_detail = {
                "sibling": {
                    "identity": repr(sibling.identity.durable_key()),
                    "empty": sibling.empty,
                }
            }
            begun = ledger.begin("database-restore", restore_detail)
            database.restore(sibling, artifact.database_dump_path())
            database.apply_runtime_ownership_and_grants(sibling)
            ledger.finish(begun, restore_detail)

        _effect(
            ledger, "target-state-and-cryptography", {"database": sibling.identity.database_name},
            lambda: target.establish(sibling, inputs),
        )
        validate_object_plan(inputs.object_entries, destination_prefix=destination_prefix)
        _effect(
            ledger, "object-prefix-reservation", {"prefix": destination_prefix},
            lambda: object_store.reserve_prefix(destination_prefix),
        )
        if inputs.object_entries and storage_makerspace is None:
            raise TenantRestoreRefused("Target storage accounting is unavailable.")
        for index, entry in enumerate(inputs.object_entries):
            if not _done(ledger, object_phase(index, entry)):
                load_object(
                    ledger, object_store, artifact, entry, index=index,
                    makerspace=storage_makerspace,
                )

        _effect(
            ledger, "api-client-reissue", {"approved": True},
            lambda: target.reissue_api_clients(sibling, inputs),
        )
        _effect(
            ledger, "target-superadmin", {"email_supplied": bool(inputs.superadmin_email)},
            lambda: target.create_superadmin(sibling, inputs),
        )
        _effect(
            ledger, "activation-verify", {"d8_verifier": "required"},
            lambda: target.verify_activation(sibling, inputs),
        )
        cutover = _cutover(ledger, pointer, database, sibling)

        def clear_gates():
            result = target.set_normal(sibling)
            marker = writers.clear_gates(sibling)
            return {"recovery": result, "host_marker": marker}

        _effect(ledger, "activation-clear-gates", {"cutover_generation": cutover["new_generation"]}, clear_gates)

        start_serving(
            ledger, inputs=inputs, sibling=sibling, cutover_detail=cutover,
            writers=writers, scheduler=scheduler,
        )

        def finalize():
            session.terminal(capability_journal, reason="lane-d-finalized")
            return {"complete": True, "lock_still_held": not session.lock_handle.closed}

        _effect(ledger, "finalize", {"complete": False}, finalize)
        return {"run_id": inputs.run_id, "generation": cutover["new_generation"]}
