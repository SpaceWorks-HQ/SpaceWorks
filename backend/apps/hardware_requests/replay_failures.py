"""Safe, bounded protocol failures. Never return or persist raw exception text."""

from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.evidence.storage import EvidenceObjectValidationError, StorageUnavailable
from apps.hardware_requests import workflow_errors as errors
from apps.inventory.availability import InsufficientStock
from apps.presence.guard import MemberPresenceRequired, PresenceRequired, WaiverAcceptanceRequired


CATALOG = {
    "rate_limited": (429, "Replay rate limit exceeded."),
    "invalid_command": (400, "Invalid replay envelope or domain payload."),
    "idempotency_conflict": (409, "This command identity or stream position has a different payload."),
    "command_expired": (409, "The command is too old or its lease has expired."),
    "clock_skew": (400, "The command timestamp is too far in the future."),
    "lease_expired": (403, "The operator lease is expired or revoked."),
    "station_revoked": (403, "The Station credential is disabled or rotated."),
    "session_mismatch": (403, "The Station session or command owner does not match."),
    "feature_disabled": (400, "This kiosk feature is disabled."),
    "module_disabled": (400, "A required kiosk module is disabled."),
    "permission_revoked": (403, "The operator no longer has permission for this operation."),
    "predecessor_missing": (409, "The immediate predecessor is missing or belongs to another stream."),
    "predecessor_pending": (409, "The preceding command has not succeeded yet."),
    "predecessor_failed": (409, "The preceding command failed."),
    "evidence_missing": (409, "The evidence has not been uploaded."),
    "evidence_invalid": (400, "The evidence is invalid, expired or already consumed."),
    "claim_in_progress": (409, "Another caller is executing this command."),
    "unsupported_operation_version": (400, "This replay operation or version is unsupported."),
    "qr_revoked": (409, "The scanned QR is no longer active in this makerspace."),
    "qr_mismatch": (400, "The scanned QR does not match this handover."),
    "request_state_changed": (409, "The request is no longer in the required state."),
    "loan_state_changed": (409, "The direct loan is no longer in the required state."),
    "deposit_unsettled": (409, "The blocking deposit must be settled before issue."),
    "presence_expired": (403, "The borrower needs an active presence session."),
    "membership_required": (403, "The borrower needs an active membership."),
    "waiver_required": (403, "The borrower must accept the current waiver."),
    "box_scan_required": (400, "A recorded box scan is required before issue."),
    "box_mismatch": (400, "The box does not match this loan or is unavailable."),
    "inventory_unavailable": (409, "The requested inventory is no longer available."),
    "storage_unavailable": (503, "Evidence storage is temporarily unavailable."),
    "server_unavailable": (503, "Replay is temporarily unavailable. Retry the same command."),
    "target_missing": (400, "The handover target does not exist in this makerspace."),
    "domain_invalid": (400, "The current handover payload cannot be applied."),
}
TRANSIENT = {"storage_unavailable", "server_unavailable", "claim_in_progress", "predecessor_pending"}


class ReplayFailure(Exception):
    def __init__(self, code):
        self.code = code
        self.status, self.detail = CATALOG[code]
        super().__init__(self.detail)


def mapped_failure(exc, kind):
    if isinstance(exc, ReplayFailure):
        return exc
    if isinstance(exc, StorageUnavailable):
        return ReplayFailure("storage_unavailable")
    if isinstance(exc, EvidenceObjectValidationError):
        return ReplayFailure("evidence_missing" if exc.code == "missing" else "evidence_invalid")
    class_codes = (
        (errors.DepositRequired, "deposit_unsettled"),
        (errors.EvidenceNotUploaded, "evidence_missing"),
        (InsufficientStock, "inventory_unavailable"),
        (PresenceRequired, "presence_expired"),
        (MemberPresenceRequired, "membership_required"),
        (WaiverAcceptanceRequired, "waiver_required"),
        (errors.RequesterBlocked, "permission_revoked"),
        (PermissionDenied, "permission_revoked"),
        (Http404, "target_missing"),
        (errors.BoxValidationError, "box_mismatch"),
        (errors.BoxUnavailable, "box_mismatch"),
        (ValidationError, "domain_invalid"),
    )
    for cls, code in class_codes:
        if isinstance(exc, cls):
            return ReplayFailure(code)
    if isinstance(exc, (errors.RequestValidationError, errors.ReturnValidationError, errors.InvalidTransition)):
        message = str(exc)
        exact = {
            "Box scan required before issue.": "box_scan_required",
            "Scanned box does not match this loan.": "box_mismatch",
            "QR code is not active for this makerspace.": "qr_revoked",
            "Scanned QR does not match this direct loan.": "qr_mismatch",
            "Return QR scan is required.": "qr_mismatch",
            "Direct loan is not currently checked out.": "loan_state_changed",
            "Tool is not currently available.": "inventory_unavailable",
            "Asset is not available for public self-checkout.": "inventory_unavailable",
            "The same QR code was scanned more than once.": "qr_mismatch",
            "Scanned box does not match the selected container.": "qr_mismatch",
            "Individual-tracked products require scanned asset QR codes for handout.": "qr_mismatch",
        }
        code = exact.get(message)
        if code is None and message.startswith("Cannot ") and "hardware request with status" in message:
            code = "request_state_changed"
        if code is None and "evidence" in message.lower():
            code = "evidence_invalid"
        if code is None:
            code = "loan_state_changed" if isinstance(exc, errors.InvalidTransition) and kind.startswith("direct_") else "domain_invalid"
        return ReplayFailure(code)
    return None
