from collections import defaultdict

from django.db.models import Q

from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests.display import requester_label
from apps.hardware_requests.models import HardwareRequestItem, PublicToolLoan
from apps.hardware_requests.timeline_service_requests import (
    DEFAULT_LIMIT,
    _asset_link_events,
    _event,
    _ordered,
    _qr_scan_events,
    _return_events,
)
from apps.inventory.models import InventoryAsset, TrackingMode


def build_inventory_chain_of_custody(product, *, limit=DEFAULT_LIMIT):
    items = list(
        HardwareRequestItem.objects.filter(product=product, request__makerspace_id=product.makerspace_id).filter(Q(request__accepted_at__isnull=False) | Q(issued_quantity__gt=0))
        .select_related("request", "request__requester", "request__accepted_by", "request__issued_by", "request__issue_evidence", "request__public_tool_loan", "product")
        .prefetch_related("asset_links__asset")
        .order_by("-request__issued_at", "-request__created_at", "-pk")[:limit]
    )
    requests = {item.request_id: item.request for item in items}
    loans = _product_public_loans(product, requests, limit)
    requests.update({loan.request_id: loan.request for loan in loans})
    request_ids = list(requests)
    events = []
    for item in items:
        events.extend(_loan_item_events(item))
        events.extend(_asset_link_events([item]))
    for loan in loans:
        events.extend(_direct_loan_events(loan))
    if request_ids:
        events.extend(_return_events(request_ids))
    events.extend(_product_qr_scan_events(product))
    events.extend(_evidence_events_for_requests(requests.values()))
    ordered, truncated = _ordered(events, limit)
    return {
        "product_id": product.pk,
        "product_name": product.name,
        "tracking_mode": product.tracking_mode,
        "limit": limit,
        "truncated": truncated,
        "events": ordered,
        "asset_groups": _asset_groups(product, ordered) if product.tracking_mode == TrackingMode.INDIVIDUAL else [],
        "quantity_summary": _quantity_summary(items, loans) if product.tracking_mode == TrackingMode.QUANTITY else None,
    }


def _loan_item_events(item):
    request = item.request
    return [
        _event(
            "direct_loan" if hasattr(request, "public_tool_loan") else "request_accepted",
            request.issued_at or request.accepted_at or request.created_at,
            request.issued_by or request.accepted_by,
            item.pk,
            {"request_id": request.pk, "request_item_id": item.pk, "product_id": item.product_id, "product_name": item.product.name, "requester": requester_label(request), "accepted_quantity": item.accepted_quantity, "issued_quantity": item.issued_quantity, "returned_quantity": item.returned_quantity, "damaged_quantity": item.damaged_quantity, "missing_quantity": item.missing_quantity},
        )
    ]


def _direct_loan_events(loan):
    return [
        _event(
            "direct_loan",
            loan.checked_out_at,
            loan.request.issued_by,
            loan.pk,
            {"loan_id": loan.pk, "request_id": loan.request_id, "source": loan.source, "status": loan.status, "target_label": loan.target_label, "requester": requester_label(loan.request), "returned_at": loan.returned_at},
        )
    ]


def _product_public_loans(product, requests, limit):
    asset_ids = set(product.assets.values_list("id", flat=True))
    loans = PublicToolLoan.objects.filter(makerspace_id=product.makerspace_id).select_related("request", "request__issued_by", "request__issue_evidence", "requester").order_by("-checked_out_at", "-pk")[:limit]
    matched = []
    for loan in loans:
        loan_assets = {int(asset_id) for asset_id in (loan.asset_ids or [])}
        if loan.request_id in requests or (loan.target_type == "product" and loan.target_id == product.pk) or bool(loan_assets & asset_ids):
            matched.append(loan)
    return matched


def _product_qr_scan_events(product):
    asset_ids = list(product.assets.values_list("id", flat=True))
    qrs = QrCode.objects.filter(makerspace_id=product.makerspace_id, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk)
    if asset_ids:
        qrs = qrs | QrCode.objects.filter(makerspace_id=product.makerspace_id, target_type=QrCode.TargetType.ASSET, target_id__in=asset_ids)
    return _qr_scan_events(QrScanEvent.objects.filter(qr_code__in=qrs))


def _evidence_events_for_requests(requests):
    events = []
    for request in requests:
        if request.issue_evidence_id:
            events.append(_event("issue_evidence", request.issued_at or request.issue_evidence.created_at, request.issued_by, request.issue_evidence_id, {"request_id": request.pk, "remark": request.issue_remark}, evidence_id=request.issue_evidence_id))
    return events


def _asset_groups(product, events):
    assets = {asset.pk: asset for asset in InventoryAsset.objects.filter(product=product).order_by("asset_tag", "pk")}
    grouped = defaultdict(list)
    for event in events:
        asset_id = event["detail"].get("asset_id")
        if asset_id is not None:
            grouped[asset_id].append(event)
    return [{"asset_id": asset_id, "asset_tag": asset.asset_tag, "serial_number": asset.serial_number, "status": asset.status, "events": grouped[asset_id]} for asset_id, asset in assets.items() if grouped.get(asset_id)]


def _quantity_summary(items, loans):
    return {
        "loan_count": len({item.request_id for item in items}),
        "direct_loan_count": len(loans),
        "issued_quantity": sum(item.issued_quantity for item in items),
        "returned_quantity": sum(item.returned_quantity for item in items),
        "damaged_quantity": sum(item.damaged_quantity for item in items),
        "missing_quantity": sum(item.missing_quantity for item in items),
        "active_quantity": sum(item.issued_quantity - item.returned_quantity - item.damaged_quantity - item.missing_quantity for item in items),
    }
