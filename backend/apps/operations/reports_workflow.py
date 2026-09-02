from collections import defaultdict

from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.makerspaces.anonymous_requesters import anonymous_requester_ids
from apps.makerspaces.platform import module_enabled
from apps.operations.report_scope import scoped_ids
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import apply_range, limited, report_spaces


FIELDS = (
    "period", "source", "request_status", "request_count", "unique_borrowers",
    "anonymous_requests", "requested_units", "accepted_units", "issued_units",
    "returned_units", "damaged_units", "missing_units", "average_approval_hours",
    "average_loan_hours",
)


def build_loan_throughput(makerspace_id, *, limit=None, date_range=None, grain="day"):
    aggregate = makerspace_id is None
    spaces = list(report_spaces(makerspace_id))
    space_ids = [space.id for space in spaces]
    direct_enabled = {space.id for space in spaces if module_enabled(space, "guest_handover")}
    sources = dict(PublicToolLoan.objects.filter(
        makerspace_id__in=direct_enabled
    ).values_list("request_id", "source"))
    requests = apply_range(
        HardwareRequest.objects.filter(makerspace_id__in=space_ids).prefetch_related("items"),
        "created_at", date_range,
    ).order_by("created_at", "id")
    sentinels = anonymous_requester_ids(space_ids)
    groups = defaultdict(_empty_group)
    for request in requests.iterator(chunk_size=200):
        period = request.created_at.date().replace(day=1) if grain == "month" else request.created_at.date()
        source = sources.get(request.id, "request_workflow")
        key = (request.makerspace_id if aggregate else None, period, source, request.status)
        row = groups[key]
        row["request_count"] += 1
        if request.requester_id in sentinels:
            row["anonymous_requests"] += 1
        else:
            row["_borrowers"].add(request.requester_id)
        for item in request.items.all():
            for source_field, target_field in (
                ("requested_quantity", "requested_units"),
                ("accepted_quantity", "accepted_units"),
                ("issued_quantity", "issued_units"),
                ("returned_quantity", "returned_units"),
                ("damaged_quantity", "damaged_units"),
                ("missing_quantity", "missing_units"),
            ):
                row[target_field] += getattr(item, source_field)
        if request.accepted_at:
            row["_approval_seconds"].append((request.accepted_at - request.created_at).total_seconds())
        if request.issued_at and request.closed_at:
            row["_loan_seconds"].append((request.closed_at - request.issued_at).total_seconds())
    records = []
    for key, row in sorted(groups.items(), key=lambda item: item[0]):
        space_id, period, source, status = key
        record = {
            "period": period, "source": source, "request_status": status,
            **{field: row[field] for field in (
                "request_count", "anonymous_requests", "requested_units",
                "accepted_units", "issued_units", "returned_units",
                "damaged_units", "missing_units",
            )},
            "unique_borrowers": len(row["_borrowers"]),
            "average_approval_hours": _average_hours(row["_approval_seconds"]),
            "average_loan_hours": _average_hours(row["_loan_seconds"]),
        }
        if aggregate:
            record["makerspace_id"] = space_id
        records.append(record)
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))


def _empty_group():
    return {
        "request_count": 0, "anonymous_requests": 0, "requested_units": 0,
        "accepted_units": 0, "issued_units": 0, "returned_units": 0,
        "damaged_units": 0, "missing_units": 0, "_borrowers": set(),
        "_approval_seconds": [], "_loan_seconds": [],
    }


def _average_hours(values):
    return round(sum(values) / len(values) / 3600, 2) if values else None
