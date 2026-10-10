from collections import Counter

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests import loan_payments
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItemAsset,
    RequesterAccountability,
)
from apps.hardware_requests.workflow_errors import ReturnValidationError
from apps.inventory.models import InventoryAsset, TrackingMode


OUTCOME_MAP = {
    "returned": (HardwareRequestItemAsset.Outcome.RETURNED, InventoryAsset.Status.AVAILABLE),
    "damaged": (HardwareRequestItemAsset.Outcome.DAMAGED, InventoryAsset.Status.DAMAGED),
    "missing": (HardwareRequestItemAsset.Outcome.LOST, InventoryAsset.Status.LOST),
}


def build_resolutions(locked, resolutions):
    item_ids = [resolution["item_id"] for resolution in resolutions]
    items = {
        item.pk: item
        for item in locked.items.select_related("product").filter(pk__in=item_ids)
    }
    validated = []
    total_resolved = 0
    for resolution in resolutions:
        item = items.get(resolution["item_id"])
        if item is None:
            raise ReturnValidationError("Return item does not belong to this loan.")

        returned = resolution["returned"]
        damaged = resolution["damaged"]
        missing = resolution["missing"]
        asset_outcomes = list(resolution.get("assets", []))
        if returned < 0 or damaged < 0 or missing < 0:
            raise ReturnValidationError("Return quantities cannot be negative.")

        if item.product.tracking_mode == TrackingMode.INDIVIDUAL:
            returned, damaged, missing = _individual_counts(
                item, returned, damaged, missing, asset_outcomes
            )

        quantity = returned + damaged + missing
        if quantity > remaining_quantity(item):
            raise ReturnValidationError(
                "Return quantity exceeds remaining issued quantity."
            )

        total_resolved += quantity
        validated.append(
            {
                "item": item,
                "returned": returned,
                "damaged": damaged,
                "missing": missing,
                "asset_outcomes": asset_outcomes,
            }
        )

    if total_resolved < 1:
        raise ReturnValidationError("At least one item must be resolved.")
    return validated


def _individual_counts(item, returned, damaged, missing, asset_outcomes):
    remaining = remaining_quantity(item)
    if asset_outcomes:
        counts = Counter(asset["outcome"] for asset in asset_outcomes)
        exact = (counts["returned"], counts["damaged"], counts["missing"])
        provided = (returned, damaged, missing)
        if provided != (0, 0, 0) and provided != exact:
            raise ReturnValidationError("Asset outcomes must match return quantities.")
        return exact
    if damaged or missing or returned != remaining:
        raise ReturnValidationError(
            "Individual-tracked returns require exact asset identity."
        )
    return returned, damaged, missing


def remaining_quantity(item):
    return item.issued_quantity - (
        item.returned_quantity + item.damaged_quantity + item.missing_quantity
    )


def write_accountability(actor, locked, evidence, resolutions):
    for resolution in resolutions:
        item = resolution["item"]
        _write_issue(
            actor,
            locked,
            item,
            evidence,
            RequesterAccountability.IssueType.DAMAGED,
            resolution["damaged"],
        )
        _write_issue(
            actor,
            locked,
            item,
            evidence,
            RequesterAccountability.IssueType.MISSING,
            resolution["missing"],
        )


def flip_individual_asset_returns(actor, locked, resolutions, event):
    now = timezone.now()
    for resolution in resolutions:
        item = resolution["item"]
        if item.product.tracking_mode != TrackingMode.INDIVIDUAL:
            continue
        if resolution.get("asset_outcomes"):
            _flip_exact_asset_links(
                actor, locked, item, resolution["asset_outcomes"], event, now
            )
            continue
        _flip_asset_links(
            item,
            resolution["returned"],
            HardwareRequestItemAsset.Outcome.RETURNED,
            InventoryAsset.Status.AVAILABLE,
            event,
            now,
        )


def _flip_exact_asset_links(actor, locked, item, asset_outcomes, event, now):
    requested_ids = [asset["asset_id"] for asset in asset_outcomes]
    links = {
        link.asset_id: link
        for link in HardwareRequestItemAsset.objects.select_for_update()
        .select_related("asset")
        .filter(
            request_item=item,
            asset_id__in=requested_ids,
            outcome=HardwareRequestItemAsset.Outcome.ISSUED,
        )
    }
    if len(links) != len(requested_ids):
        raise ReturnValidationError("Return asset does not belong to this issued item.")
    qr_by_asset = _active_asset_qrs(locked, requested_ids)
    for asset in asset_outcomes:
        link = links[asset["asset_id"]]
        outcome, asset_status = OUTCOME_MAP[asset["outcome"]]
        _set_link_outcome(link, outcome, asset_status, event, now)
        qr = qr_by_asset.get(link.asset_id)
        if qr is not None:
            QrScanEvent.objects.create(
                makerspace=locked.makerspace,
                qr_code=qr,
                request=locked,
                actor=actor,
                context=QrScanEvent.Context.RETURN,
            )


def _active_asset_qrs(locked, asset_ids):
    return {
        qr.target_id: qr
        for qr in QrCode.objects.filter(
            makerspace=locked.makerspace,
            target_type=QrCode.TargetType.ASSET,
            target_id__in=asset_ids,
            status=QrCode.Status.ACTIVE,
        )
    }


def _flip_asset_links(item, quantity, outcome, asset_status, event, now):
    if quantity <= 0:
        return
    links = list(
        HardwareRequestItemAsset.objects.select_for_update()
        .select_related("asset")
        .filter(request_item=item, outcome=HardwareRequestItemAsset.Outcome.ISSUED)
        .order_by("asset_id")[:quantity]
    )
    if len(links) != quantity:
        raise ReturnValidationError("Return quantity exceeds linked issued assets.")
    for link in links:
        _set_link_outcome(link, outcome, asset_status, event, now)


def _set_link_outcome(link, outcome, asset_status, event, now):
    link.asset.status = asset_status
    link.asset.save(update_fields=["status", "updated_at"])
    link.outcome = outcome
    link.returned_at = now
    link.return_event = event
    link.save(update_fields=["outcome", "returned_at", "return_event"])


def finalize_return_status(locked, actor):
    all_items = list(locked.items.all())
    all_resolved = all(
        (
            item.returned_quantity + item.damaged_quantity + item.missing_quantity
        )
        == item.issued_quantity
        for item in all_items
    )
    has_issue = any(
        item.damaged_quantity > 0 or item.missing_quantity > 0 for item in all_items
    )

    if not all_resolved:
        locked.status = HardwareRequest.Status.PARTIALLY_RETURNED
        locked.save(update_fields=["status", "updated_at"])
        return "request.partially_returned"

    locked.status = (
        HardwareRequest.Status.CLOSED_WITH_ISSUE
        if has_issue
        else HardwareRequest.Status.RETURNED
    )
    locked.closed_by = actor
    locked.closed_at = timezone.now()
    locked.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
    # Every return surface reaches this finalizer. Payments run only after the
    # return commits, so provider or ledger failures cannot undo a physical return.
    request_id = locked.pk
    transaction.on_commit(lambda: loan_payments.on_request_closed(request_id, actor))
    if has_issue:
        return "request.closed_with_issue"
    return "request.returned"


def _write_issue(actor, locked, item, evidence, issue_type, quantity):
    if quantity <= 0:
        return

    RequesterAccountability.objects.create(
        requester=locked.requester,
        request=locked,
        request_item=item,
        makerspace=locked.makerspace,
        issue_type=issue_type,
        evidence_photo=evidence,
        quantity=quantity,
        created_by=actor,
    )
    audit.record(
        actor,
        f"item.{issue_type}",
        makerspace=locked.makerspace,
        target=item,
        meta={
            "request_id": locked.pk,
            "evidence_id": evidence.pk,
            "quantity": quantity,
        },
    )
