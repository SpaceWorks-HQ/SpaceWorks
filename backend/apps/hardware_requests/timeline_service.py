from collections import defaultdict

from django.db.models import Q

from apps.boxes.models import BoxScan, QrCode, QrScanEvent
from apps.hardware_requests.display import requester_label
from apps.hardware_requests.models import (
    HardwareRequestItem,
    PublicProblemReport,
    PublicToolLoan,
    RequesterAccountability,
    ReturnEvent,
)
from apps.inventory.models import InventoryAsset, TrackingMode

DEFAULT_LIMIT = 200
MAX_LIMIT = 500
_KIND_ORDER = {
    "request_submitted": 10,
    "request_accepted": 20,
    "box_assigned": 30,
    "issue_evidence": 40,
    "box_scan": 50,
    "qr_scan": 60,
    "return_event": 70,
    "asset_outcome": 80,
    "accountability": 90,
    "problem_report": 100,
    "direct_loan": 110,
}


def build_request_timeline(hardware_request, *, limit=DEFAULT_LIMIT):
    items = list(hardware_request.items.select_related("product").prefetch_related("asset_links__asset"))
    events = [
        _event(
            "request_submitted",
            hardware_request.created_at,
            None,
            hardware_request.pk,
            {"request_id": hardware_request.pk, "status": hardware_request.status, "requester": requester_label(hardware_request)},
        )
    ]
    if hardware_request.accepted_at:
        events.append(_event("request_accepted", hardware_request.accepted_at, hardware_request.accepted_by, hardware_request.pk, {"request_id": hardware_request.pk}))
    if hardware_request.assigned_box_id:
        events.append(
            _event(
                "box_assigned",
                hardware_request.updated_at,
                None,
                hardware_request.assigned_box_id,
                {"request_id": hardware_request.pk, "box_id": hardware_request.assigned_box_id, "box_label": hardware_request.assigned_box.label},
            )
        )
    if hardware_request.issue_evidence_id:
        events.append(
            _event(
                "issue_evidence",
                hardware_request.issued_at or hardware_request.issue_evidence.created_at,
                hardware_request.issued_by,
                hardware_request.issue_evidence_id,
                {"request_id": hardware_request.pk, "remark": hardware_request.issue_remark},
                evidence_id=hardware_request.issue_evidence_id,
            )
        )
    events.extend(_box_scan_events(hardware_request.pk))
    events.extend(_qr_scan_events(QrScanEvent.objects.filter(request=hardware_request)))
    events.extend(_return_events(hardware_request.pk))
    events.extend(_asset_link_events(items))
    events.extend(_accountability_events(hardware_request.pk))
    events.extend(_problem_report_events(hardware_request))
    return _response("request_id", hardware_request.pk, events, limit)


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


def _event(kind, at, actor, source_id, detail, *, evidence_id=None):
    return {"kind": kind, "at": at, "actor": _actor_payload(actor), "detail": {"id": source_id, **detail}, "evidence_id": evidence_id, "_sort_id": source_id or 0}


def _actor_payload(actor):
    if actor is None:
        return None
    return {"username": actor.username, "role": actor.role}


def _response(id_key, id_value, events, limit):
    ordered, truncated = _ordered(events, limit)
    return {id_key: id_value, "limit": limit, "truncated": truncated, "events": ordered}


def _ordered(events, limit):
    rows = [event for event in events if event["at"] is not None]
    rows.sort(key=lambda event: (event["at"], _KIND_ORDER.get(event["kind"], 999), event["_sort_id"]))
    truncated = len(rows) > limit
    for event in rows:
        event.pop("_sort_id", None)
    return rows[:limit], truncated


def _box_scan_events(request_ids):
    scans = BoxScan.objects.filter(request_id__in=_ids(request_ids)).select_related("actor", "box")
    return [
        _event("box_scan", scan.created_at, scan.actor, scan.pk, {"request_id": scan.request_id, "box_id": scan.box_id, "box_label": scan.box.label, "context": scan.context})
        for scan in scans
    ]


def _qr_scan_events(queryset):
    scans = queryset.select_related("actor", "qr_code")
    return [
        _event(
            "qr_scan",
            scan.created_at,
            scan.actor,
            scan.pk,
            {"request_id": scan.request_id, "qr_id": scan.qr_code_id, "target_type": scan.qr_code.target_type, "target_id": scan.qr_code.target_id, "context": scan.context},
        )
        for scan in scans
    ]


def _return_events(request_ids):
    rows = ReturnEvent.objects.filter(request_id__in=_ids(request_ids)).select_related("actor", "box")
    return [
        _event(
            "return_event",
            row.created_at,
            row.actor,
            row.pk,
            {"request_id": row.request_id, "box_id": row.box_id, "box_label": row.box.label if row.box_id else "", "remark": row.remark},
            evidence_id=row.evidence_id,
        )
        for row in rows
    ]


def _asset_link_events(items):
    events = []
    for item in items:
        for link in item.asset_links.all():
            events.append(
                _event(
                    "asset_outcome",
                    link.returned_at or link.issued_at,
                    None,
                    link.pk,
                    {
                        "request_id": item.request_id,
                        "request_item_id": item.pk,
                        "product_id": item.product_id,
                        "product_name": item.product.name,
                        "asset_id": link.asset_id,
                        "asset_tag": link.asset.asset_tag,
                        "serial_number": link.asset.serial_number,
                        "outcome": link.outcome,
                    },
                )
            )
    return events


def _accountability_events(request_ids):
    rows = RequesterAccountability.objects.filter(request_id__in=_ids(request_ids)).select_related("created_by", "request_item__product")
    return [
        _event(
            "accountability",
            row.created_at,
            row.created_by,
            row.pk,
            {"request_id": row.request_id, "request_item_id": row.request_item_id, "product_id": row.request_item.product_id, "product_name": row.request_item.product.name, "issue_type": row.issue_type, "quantity": row.quantity, "description": row.description},
            evidence_id=row.evidence_photo_id,
        )
        for row in rows
    ]


def _problem_report_events(hardware_request):
    try:
        loan = hardware_request.public_tool_loan
    except PublicToolLoan.DoesNotExist:
        return []
    rows = PublicProblemReport.objects.filter(loan=loan).select_related("resolved_by")
    return [
        _event("problem_report", row.created_at, None, row.pk, {"request_id": row.request_id, "loan_id": row.loan_id, "note": row.note, "resolved_at": row.resolved_at, "resolved_by": _actor_payload(row.resolved_by)})
        for row in rows
    ]


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


def _ids(value):
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]



