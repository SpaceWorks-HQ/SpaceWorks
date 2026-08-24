"""Host-lock wrapper for the journalled compound rollback effect."""

from pathlib import Path

from apps.backup.host_run_ledger import RunLedger
from apps.backup.operation_lock import host_operation_lock

from .compound_restore_cutover import rollback_cutover
from .compound_restore_ledger import done_detail
from .compound_restore_types import CompoundRestoreRefused


def rollback_compound_restore(
    *, ops_dir, inputs, pointer, database, object_store,
    require_root_owned=True, drop_candidate=False,
):
    """Reverse cutover under the same host exclusion and retain owner evidence."""
    with host_operation_lock(
        ops_dir, require_root_owned=require_root_owned
    ):
        ledger = RunLedger(
            Path(ops_dir, "runs", f"{inputs.run_id}.jsonl"),
            run_id=inputs.run_id,
            artifact_sha256=inputs.artifact_sha256,
        )
        cutover = done_detail(ledger, "cutover")
        if cutover is None:
            raise CompoundRestoreRefused(
                "No completed compound cutover exists to roll back."
            )
        sibling = database.recover_sibling(cutover["sibling_ownership_proof"])
        return rollback_cutover(
            ledger, pointer, database, object_store, sibling,
            drop_candidate=drop_candidate,
        )
