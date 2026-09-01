"""Arm/re-arm the existing H1b candidate-backend capability."""

from datetime import timedelta

from apps.backup.host_capability_types import record_from_marker, utc_now
from apps.backup.host_marker import read_marker

from .compound_restore_types import CompoundRestoreRefused


def arm_candidate_capability(
    capability_journal, marker_writer, database, sibling, *, interrupted=False
):
    marker = read_marker(
        marker_writer.marker_path,
        require_root_owned=marker_writer.require_root_owned,
    )
    # Re-query immediately before arming. record_from_marker refuses anything
    # except this BOUND candidate-health marker.
    if marker.require_bound_database() != database.marker_identity(sibling):
        raise CompoundRestoreRefused(
            "The live candidate identity changed before capability arming."
        )
    replacement = record_from_marker(
        marker, allowed_role="backend",
        expires_at=utc_now() + timedelta(minutes=5),
    )
    if not interrupted:
        capability_journal.arm(replacement)
    else:
        capability_journal.invalidate_all("candidate-launch-interrupted")
        spent = capability_journal.latest_spent_nonce()
        if spent is None:
            raise CompoundRestoreRefused(
                "Interrupted candidate launch has no spent capability to re-arm."
            )
        capability_journal.rearm(spent, replacement)
    return {"state": "armed", "nonce": replacement.nonce}
