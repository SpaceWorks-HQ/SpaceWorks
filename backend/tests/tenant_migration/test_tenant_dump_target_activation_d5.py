import pytest

from apps.audit.models import AuditLog
from apps.tenant_migration import cutover
from apps.tenant_migration.models import MigrationReceipt
from apps.tenant_migration.protocol_errors import TransitionConflictError
from apps.tenant_migration.tenant_dump_errors import TenantDumpTargetError
from apps.tenant_migration.tenant_dump_lineage import FORMAT
from tests.tenant_migration.protocol_helpers import (
    bind_job_state,
    import_job,
    signed_envelope,
    superadmin,
    target_pairing,
)


pytestmark = pytest.mark.django_db(transaction=True)


def test_lane_d_readiness_failure_blocks_the_actual_activation_transition(
    monkeypatch,
):
    actor = superadmin("d5-activation-gate")
    pairing, source, source_private = target_pairing(actor)
    job = import_job(pairing)
    bind_job_state(monkeypatch, job)
    job.verification_report = {"format": FORMAT, "d5_ready": False}
    job.save(update_fields=("verification_report",))
    envelope = signed_envelope(
        pairing,
        MigrationReceipt.Operation.SOURCE_CUTOVER,
        source,
        source_private,
    )
    calls = []

    def failed_authenticated_samples(_makerspace_id):
        calls.append("authenticated_samples")
        raise TenantDumpTargetError(
            "Authenticated sample readiness failed.",
            code="encryption_readiness_failed",
        )

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target.run_target_encryption_readiness",
        failed_authenticated_samples,
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_dump_target.target_custody_readiness",
        lambda _makerspace_id: calls.append("custody"),
    )

    with pytest.raises((TenantDumpTargetError, TransitionConflictError)) as caught:
        cutover.activate_target(
            pairing=pairing,
            import_job=job,
            receipt_envelope=envelope,
            actor=actor,
        )

    job.target_makerspace.refresh_from_db()
    assert "readiness" in str(caught.value).lower()
    assert calls == ["authenticated_samples"]
    assert (
        job.target_makerspace.lifecycle_state
        == job.target_makerspace.LifecycleState.IMPORTING
    )
    assert not AuditLog.objects.filter(
        makerspace=job.target_makerspace,
        action="tenant_migration.target_activated",
    ).exists()
