from apps.boxes.models import BoxScan, QrScanEvent
from apps.hardware_requests.display import requester_label
from apps.hardware_requests.models import (
    PublicProblemReport,
    PublicToolLoan,
    RequesterAccountability,
    ReturnEvent,
)

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


def _ids(value):
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]

