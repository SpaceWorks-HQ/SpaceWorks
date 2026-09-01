from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.evidence.models import EvidencePhoto
from apps.evidence.finalization import charge_storage_once
from apps.hardware_requests.direct_loan_returns import validate_evidence_upload
from apps.hardware_requests.models import PublicProblemReport, RequesterAccountability
from apps.hardware_requests.workflow_errors import InvalidTransition, RequestValidationError, ReturnValidationError
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, TrackingMode


ACCOUNTABILITY_OUTCOMES = {
    PublicProblemReport.Outcome.DAMAGED: RequesterAccountability.IssueType.DAMAGED,
    PublicProblemReport.Outcome.MISSING: RequesterAccountability.IssueType.MISSING,
    PublicProblemReport.Outcome.NEEDS_FIX: RequesterAccountability.IssueType.DAMAGED,
}
ASSET_STATUS_OUTCOMES = {
    PublicProblemReport.Outcome.DAMAGED: InventoryAsset.Status.DAMAGED,
    PublicProblemReport.Outcome.MISSING: InventoryAsset.Status.DAMAGED,
    PublicProblemReport.Outcome.NEEDS_FIX: InventoryAsset.Status.MAINTENANCE,
}


def triage_problem_report(report, actor, *, outcome, resolutions, note, evidence_id=None):
    note = str(note or "").strip()
    if report.resolved_at is not None:
        raise InvalidTransition("Problem report has already been triaged.")
    evidence = _evidence(report, evidence_id)
    finalized = (
        validate_evidence_upload(evidence, label="Triage") if evidence is not None else None
    )
    with transaction.atomic():
        locked = (
            PublicProblemReport.objects.select_for_update()
            .select_related("loan", "request", "requester", "makerspace")
            .get(pk=report.pk)
        )
        if locked.resolved_at is not None:
            raise InvalidTransition("Problem report has already been triaged.")

        if finalized is not None:
            charge_storage_once(evidence, finalized.size)
        quantities = []
        if outcome != PublicProblemReport.Outcome.NO_ISSUE:
            validated = _validated_resolutions(locked, resolutions)
            for resolution in validated:
                _move_stock(actor, locked, outcome, resolution)
                _write_accountability(actor, locked, outcome, resolution, note, evidence)
                quantities.append(
                    {
                        "item_id": resolution["item"].id,
                        "quantity": resolution["quantity"],
                    }
                )
        locked.outcome = outcome
        locked.triage_note = note
        locked.resolved_at = timezone.now()
        locked.resolved_by = actor
        locked.save(update_fields=["outcome", "triage_note", "resolved_at", "resolved_by"])
        audit.record(
            actor,
            "problem_report.triaged",
            makerspace=locked.makerspace,
            target=locked,
            meta={
                "outcome": outcome,
                "quantities": quantities,
                "loan_id": locked.loan_id,
                "request_id": locked.request_id,
                "evidence_id": evidence.id if evidence else None,
            },
        )
        return locked


def _evidence(report, evidence_id):
    if evidence_id in (None, ""):
        return None
    try:
        evidence_pk = int(evidence_id)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError("Invalid evidence.") from exc
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_pk,
        makerspace=report.makerspace,
    ).first()
    if evidence is None:
        raise RequestValidationError("Invalid evidence.")
    return evidence


def _validated_resolutions(report, resolutions):
    if not resolutions:
        raise ReturnValidationError("At least one item must be triaged.")
    item_ids = [entry["item_id"] for entry in resolutions]
    items = {
        item.id: item
        for item in report.request.items.select_for_update()
        .select_related("product")
        .filter(pk__in=item_ids)
    }
    validated = []
    total = 0
    for entry in resolutions:
        item = items.get(entry["item_id"])
        if item is None:
            raise ReturnValidationError("Problem report item does not belong to this loan.")
        quantity = int(entry["quantity"])
        if quantity <= 0:
            raise ReturnValidationError("Triage quantity must be positive.")
        if quantity > item.issued_quantity:
            raise ReturnValidationError("Triage quantity exceeds issued quantity for this item.")
        total += quantity
        validated.append({"item": item, "quantity": quantity})
    if total < 1:
        raise ReturnValidationError("At least one item must be triaged.")
    return validated


def _move_stock(actor, report, outcome, resolution):
    item = resolution["item"]
    quantity = resolution["quantity"]
    if item.product.tracking_mode == TrackingMode.INDIVIDUAL:
        _move_individual_assets(report, item, quantity, ASSET_STATUS_OUTCOMES[outcome])
        return
    availability.move_available_to_triage_bucket(
        item.product,
        quantity,
        outcome=outcome,
        reason=f"Public problem report #{report.id}: {outcome}",
        actor=actor,
    )


def _move_individual_assets(report, item, quantity, target_status):
    assets = list(
        InventoryAsset.objects.select_for_update()
        .filter(
            pk__in=report.loan.asset_ids,
            makerspace=report.makerspace,
            product=item.product,
            status=InventoryAsset.Status.AVAILABLE,
        )
        .order_by("pk")[:quantity]
    )
    if len(assets) != quantity:
        raise ReturnValidationError("Triage quantity exceeds returned assets for this item.")
    for asset in assets:
        availability.move_asset_status(asset, target_status)


def _write_accountability(actor, report, outcome, resolution, note, evidence):
    quantity = resolution["quantity"]
    if quantity <= 0:
        return
    item = resolution["item"]
    issue_type = ACCOUNTABILITY_OUTCOMES[outcome]
    RequesterAccountability.objects.create(
        requester=report.requester,
        request=report.request,
        request_item=item,
        makerspace=report.makerspace,
        issue_type=issue_type,
        description=note,
        evidence_photo=evidence,
        quantity=quantity,
        created_by=actor,
    )
    audit.record(
        actor,
        f"item.{issue_type}",
        makerspace=report.makerspace,
        target=item,
        meta={
            "request_id": report.request_id,
            "problem_report_id": report.id,
            "outcome": outcome,
            "evidence_id": evidence.id if evidence else None,
            "quantity": quantity,
        },
    )
