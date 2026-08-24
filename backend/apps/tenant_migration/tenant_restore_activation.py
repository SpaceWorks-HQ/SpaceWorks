"""Crash-safe D7 pointer cutover and writer activation effects."""

from .tenant_restore_ledger import done_detail, incomplete_effect, phase_done
from .tenant_restore_scheduler import assert_same_fence_receipt, receipt_from_detail
from .tenant_restore_types import TenantRestoreRefused


def cutover(ledger, pointer, database, sibling):
    phase = "activation-cutover"
    if phase_done(ledger, phase):
        detail = done_detail(ledger, phase)
        if not (
            pointer.record_matches(detail)
            and database.database_marker_matches(sibling, detail["new_database_marker"])
        ):
            raise TenantRestoreRefused("Completed cutover pointer or marker changed.")
        return detail
    prior = incomplete_effect(ledger, phase)
    detail = prior["detail"] if prior is not None else pointer.cutover_detail(sibling)
    if (
        prior is not None
        and pointer.record_matches(detail)
        and database.database_marker_matches(sibling, detail["new_database_marker"])
    ):
        ledger.finish(prior, detail)
        return detail
    begun = ledger.begin(phase, detail)
    pointer.compare_and_swap(detail)
    if not (
        pointer.record_matches(detail)
        and database.database_marker_matches(sibling, detail["new_database_marker"])
    ):
        raise TenantRestoreRefused("Pointer cutover did not commit pointer and marker together.")
    ledger.finish(begun, detail)
    return detail


def start_serving(ledger, *, inputs, sibling, cutover_detail, writers, scheduler):
    phase = "activation-start-serving"
    if phase_done(ledger, phase):
        return done_detail(ledger, phase)
    prior = incomplete_effect(ledger, phase)
    begun = ledger.begin(phase, {
        "gates_cleared": True,
        "resume_refence": prior is not None and scheduler is not None,
    })
    new_identity = cutover_detail["new_database_marker"]
    generation = cutover_detail["new_generation"]
    scheduler_result = None
    if scheduler is not None:
        if prior is not None:
            expected = receipt_from_detail(
                done_detail(ledger, "external-scheduler-fence")
            )
            actual = scheduler.status(run_id=inputs.run_id)
            if actual != expected:
                stopped = scheduler.stop(
                    run_id=inputs.run_id,
                    old_identity=new_identity,
                    old_generation=generation,
                )
                receipt = scheduler.fence(
                    run_id=inputs.run_id,
                    expected_scheduler_generation=stopped["pre_stop_generation"],
                )
                assert_same_fence_receipt(
                    receipt, scheduler.status(run_id=inputs.run_id)
                )
        scheduler.restart(
            run_id=inputs.run_id,
            new_identity=new_identity,
            new_generation=generation,
        )
        scheduler_result = scheduler.readiness(
            run_id=inputs.run_id,
            new_identity=new_identity,
            new_generation=generation,
        )
    writer_result = writers.start(sibling, generation)
    detail = {"writers": writer_result, "scheduler": scheduler_result}
    ledger.finish(begun, detail)
    return detail
