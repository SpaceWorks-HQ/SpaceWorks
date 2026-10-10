"""Shared evidence ownership and single-use checks for self-checkout."""

from apps.evidence.finalization import lock_evidence_for_attachment
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan, ReturnEvent
from apps.hardware_requests.workflow_errors import RequestValidationError, ReturnValidationError


def _public_evidence(makerspace, requester, evidence_id, evidence_type):
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_id,
        makerspace=makerspace,
        evidence_type=evidence_type,
        uploaded_by=requester,
    ).first()
    if evidence is None:
        raise RequestValidationError("Invalid evidence.")
    return evidence


def _lock_unused_evidence(evidence, *, issue):
    if not lock_evidence_for_attachment(evidence.pk):
        error = RequestValidationError if issue else ReturnValidationError
        raise error("Evidence has expired under the retention policy.")
    if issue:
        if HardwareRequest.objects.filter(issue_evidence=evidence).exists():
            raise RequestValidationError("Evidence already used.")
        return
    if (
        PublicToolLoan.objects.filter(return_evidence=evidence).exists()
        or ReturnEvent.objects.filter(evidence=evidence).exists()
    ):
        raise ReturnValidationError("Evidence already used.")


