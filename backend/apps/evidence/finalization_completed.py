"""Database-only finalized evidence reuse inside a consuming transaction."""

from apps.evidence.models import EvidenceObjectRetentionState, EvidenceUploadFinalization


def completed_result(evidence):
    from apps.evidence.finalization import _result
    from apps.evidence.storage import EvidenceObjectValidationError

    state = EvidenceUploadFinalization.objects.filter(
        evidence_id=evidence.pk, status=EvidenceUploadFinalization.Status.FINALIZED,
    ).first()
    if state is None:
        return None
    # This is a read, not attachment. Reviewed workflows lock request -> evidence;
    # taking evidence first here would invert that order under replay's outer atomic.
    # Each consuming workflow still takes its authoritative retention/attachment locks.
    if EvidenceObjectRetentionState.objects.filter(evidence_id=evidence.pk).exists():
        raise EvidenceObjectValidationError("expired", "Evidence has expired.")
    return _result(state)
