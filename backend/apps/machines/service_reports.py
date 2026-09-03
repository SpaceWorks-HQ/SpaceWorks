"""Canonical, PII-free reporting rows for machine service work."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, DecimalField, ExpressionWrapper, F, FloatField, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.machines import role_scope
from apps.machines.models import Machine, MachineServiceRequest, MachineUsageEntry, ServiceRequestConsumption
from apps.machines.printer_capabilities import resolve_global_printer_type
from apps.payments.models import Payment
from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import scoped_ids


CENT = Decimal("0.01")
COMPLETED = (MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.COLLECTED)
FIELDS = (
    "row_kind", "submitted", "accepted", "in_progress", "completed", "collected", "rejected", "failed",
    "machine_id", "machine_name", "machine_type", "request_count", "completed_count", "failed_count",
    "completed_hours", "failed_partial_hours", "total_recorded_service_hours", "failure_rate",
    "measurement", "product_id", "product_label", "completed_amount", "failed_partial_amount", "total_used",
    "outcome", "failed_count_amount", "failed_grams_amount",
)


def _request_scope_q(machine_scope, prefix=""):
    """Scope Q for a MachineServiceRequest, optionally reached through a relation.

    Mirrors `role_scope.SERVICE_REQUEST_*_PATHS`, prefixed for callers that reach the
    request through a FK (the consumption ledger). `None` means "no actor to scope by"
    -- the report registry and the superadmin aggregate -- and matches everything.
    """
    if machine_scope is None:
        return Q()
    return role_scope.scope_q_for(
        machine_scope,
        machine_id_paths=tuple(
            f"{prefix}{path}" for path in role_scope.SERVICE_REQUEST_MACHINE_PATHS
        ),
        type_id_paths=tuple(
            f"{prefix}{path}" for path in role_scope.SERVICE_REQUEST_TYPE_PATHS
        ),
    )


def build_machine_service_report(makerspace_id, *, limit=None, date_range=None, machine_scope=None):
    """Build flat rows so registry JSON/export consumers share one report source.

    ``machine_scope`` is a resolved `role_scope` scope for a staff caller whose
    MANAGE_MACHINES grant is narrowed to some of the lab's machines. Left ``None`` by the
    report registry and the superadmin aggregate, where there is no single actor to scope
    by -- and an exempt actor resolves to an empty Q, so their report is unchanged.
    """
    aggregate = makerspace_id is None
    ids = scoped_ids(makerspace_id, "machine_service")
    status_rows = _status_rows(ids, aggregate, date_range, machine_scope)
    machine_rows = _machine_rows(ids, aggregate, date_range, machine_scope)
    consumption_rows = _consumption_rows(ids, aggregate, date_range, machine_scope)
    failed_usage = _failed_usage(consumption_rows)
    records = [*status_rows, *machine_rows, *consumption_rows]
    records.extend(_failure_rows(machine_rows, failed_usage, aggregate))
    records.sort(key=lambda row: _sort_key(row, aggregate))
    if limit is not None:
        records = records[:limit]
    fields = (("makerspace_id",) if aggregate else ()) + FIELDS
    return ReportResult(fields, records)


def build_printer_service_report(makerspace_id, *, limit=None, date_range=None, machine_scope=None):
    """Type-pack projection for printer hours, filament and payment snapshots.

    It is intentionally a report-registry builder seam, not a printer endpoint:
    the generic service report remains unchanged for non-printer machines.
    """
    ids = scoped_ids(makerspace_id, "printing")
    aggregate = makerspace_id is None
    terminal = Q(status__in=COMPLETED) | Q(status=MachineServiceRequest.Status.FAILED)
    printer_type = resolve_global_printer_type()
    if printer_type is None:
        requests = MachineServiceRequest.objects.none()
    else:
        requests = MachineServiceRequest.objects.filter(
            makerspace_id__in=ids,
            assigned_machine__machine_type=printer_type,
        ).filter(_request_scope_q(machine_scope)).filter(terminal).order_by()
    if date_range:
        requests = requests.filter(_date_filter("completed_at", date_range) | _date_filter("failed_at", date_range))
    payment_totals = defaultdict(lambda: [Decimal("0.00"), Decimal("0.00")])
    request_machines = {
        request_id: ((space_id, machine_id) if aggregate else machine_id)
        for request_id, space_id, machine_id in requests.values_list("id", "makerspace_id", "assigned_machine_id")
    }
    for payment in Payment.objects.filter(makerspace_id__in=ids, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST, subject_id__in=request_machines):
        key = request_machines[payment.subject_id]
        if payment.status == Payment.Status.PENDING:
            payment_totals[key][0] += payment.amount
        elif payment.status in {Payment.Status.PAID_ONLINE, Payment.Status.PAID_OFFLINE}:
            payment_totals[key][1] += payment.amount
    values = ["assigned_machine_id", "assigned_machine__name", "run_machine_model"]
    if aggregate:
        values.insert(0, "makerspace_id")
    rows = requests.values(*values).annotate(
        completed_minutes=Coalesce(Sum("actual_minutes", filter=Q(status__in=COMPLETED)), Value(0)),
        failed_minutes=Coalesce(Sum(ExpressionWrapper(F("actual_minutes") * F("fail_percent_complete") / Value(100.0), output_field=FloatField()), filter=Q(status=MachineServiceRequest.Status.FAILED)), Value(0.0)),
        grams=Coalesce(Sum("actual_consumed_grams"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))),
        payment_due=Coalesce(Sum("payment_amount", filter=Q(payment_status="pending")), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))),
        payment_paid=Coalesce(Sum("payment_amount", filter=Q(payment_status="paid")), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))),
    )
    if printer_type is None:
        manual = MachineUsageEntry.objects.none()
    else:
        manual = MachineUsageEntry.objects.filter(
            machine__makerspace_id__in=ids,
            machine__machine_type=printer_type,
            source=MachineUsageEntry.Source.TYPED_MANUAL,
        ).order_by()
    if date_range:
        manual = manual.filter(_date_filter("created_at", date_range))
    manual_values = ["machine_id"] + (["machine__makerspace_id"] if aggregate else [])
    manual_hours = {
        ((item["machine__makerspace_id"], item["machine_id"]) if aggregate else item["machine_id"]): item["hours"]
        for item in manual.values(*manual_values).annotate(hours=Coalesce(Sum("hours"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=10, decimal_places=2))))
    }
    records = []
    for row in rows:
        key = (row["makerspace_id"], row["assigned_machine_id"]) if aggregate else row["assigned_machine_id"]
        record = {
            "machine_id": row["assigned_machine_id"], "machine_name": row["assigned_machine__name"], "model": row["run_machine_model"],
            "completed_hours": _hours(row["completed_minutes"]), "failed_partial_hours": _hours(row["failed_minutes"]),
            "manual_hours": float(manual_hours.get(key, Decimal("0"))), "consumed_grams": _amount(row["grams"]),
            "payment_due": _amount(payment_totals[key][0]), "payment_paid": _amount(payment_totals[key][1]),
        }
        if aggregate:
            record["makerspace_id"] = row["makerspace_id"]
        records.append(record)
    records.sort(key=lambda row: ((row.get("makerspace_id"),) if aggregate else ()) + (row["machine_name"], row["machine_id"]))
    if limit is not None:
        records = records[:limit]
    fields = ("makerspace_id",) if aggregate else ()
    return ReportResult(fields + ("machine_id", "machine_name", "model", "completed_hours", "failed_partial_hours", "manual_hours", "consumed_grams", "payment_due", "payment_paid"), records)


def report_sections(result):
    """Project canonical rows into the dedicated staff API's explicit sections."""
    sections = {"status_totals": [], "machines": [], "consumption": [], "failure_summary": []}
    targets = {"status": "status_totals", "machine": "machines", "consumption": "consumption", "failure": "failure_summary"}
    for record in result.records:
        clean = {key: value for key, value in record.items() if key != "row_kind"}
        sections[targets[record["row_kind"]]].append(clean)
    return sections


def _status_rows(ids, aggregate, date_range, machine_scope=None):
    created = _date_filter("created_at", date_range)
    # .order_by() strips the model's Meta ordering (by created_at) so it can't leak
    # into the GROUP BY of the values()/annotate() aggregation.
    requests = MachineServiceRequest.objects.filter(
        makerspace_id__in=ids
    ).filter(_request_scope_q(machine_scope)).order_by()
    rows = requests.values("makerspace_id") if aggregate else requests.annotate(_group=Value(1)).values("_group")
    rows = rows.annotate(
        submitted=Count("id", filter=created),
        accepted=Count("id", filter=created & Q(status=MachineServiceRequest.Status.ACCEPTED)),
        in_progress=Count("id", filter=created & Q(status=MachineServiceRequest.Status.IN_PROGRESS)),
        completed=Count("id", filter=created & Q(status=MachineServiceRequest.Status.COMPLETED)),
        collected=Count("id", filter=created & Q(status=MachineServiceRequest.Status.COLLECTED)),
        rejected=Count("id", filter=created & Q(status=MachineServiceRequest.Status.REJECTED)),
        failed=Count("id", filter=created & Q(status=MachineServiceRequest.Status.FAILED)),
    )
    return [_record("status", row, aggregate) for row in rows]


def _machine_rows(ids, aggregate, date_range, machine_scope=None):
    created = _date_filter("created_at", date_range)
    completed = _date_filter("completed_at", date_range)
    failed = _date_filter("failed_at", date_range)
    requests = MachineServiceRequest.objects.filter(
        assigned_machine_id=OuterRef("pk"), makerspace_id=OuterRef("makerspace_id"),
    ).order_by().values("assigned_machine_id")
    partial_minutes = ExpressionWrapper(
        F("estimated_minutes") * F("fail_percent_complete") / Value(100.0), output_field=FloatField()
    )
    stats = requests.annotate(
        requested=Count("id", filter=created),
        completed_count=Count("id", filter=completed & Q(status__in=COMPLETED)),
        failed_count=Count("id", filter=failed & Q(status=MachineServiceRequest.Status.FAILED)),
        completed_minutes=Coalesce(Sum("actual_minutes", filter=completed & Q(status__in=COMPLETED)), Value(0)),
        failed_minutes=Coalesce(Sum(partial_minutes, filter=failed & Q(status=MachineServiceRequest.Status.FAILED)), Value(0.0)),
    )
    qs = Machine.objects.filter(
        makerspace_id__in=ids,
        assigned_service_requests__assigned_machine__makerspace_id=F("makerspace_id"),
    ).filter(
        role_scope.scope_q_for(
            machine_scope, machine_id_paths=("id",), type_id_paths=("machine_type_id",)
        ) if machine_scope is not None else Q()
    ).order_by().distinct().values("id", "makerspace_id", "name", "machine_type__name").annotate(
        requested=Coalesce(Subquery(stats.values("requested")[:1], output_field=IntegerField()), Value(0)),
        completed_count=Coalesce(Subquery(stats.values("completed_count")[:1], output_field=IntegerField()), Value(0)),
        failed_count=Coalesce(Subquery(stats.values("failed_count")[:1], output_field=IntegerField()), Value(0)),
        completed_minutes=Coalesce(Subquery(stats.values("completed_minutes")[:1], output_field=IntegerField()), Value(0)),
        failed_minutes=Coalesce(Subquery(stats.values("failed_minutes")[:1], output_field=FloatField()), Value(0.0)),
    )
    return [_record("machine", row, aggregate) for row in qs]


def _consumption_rows(ids, aggregate, date_range, machine_scope=None):
    completed = _date_filter("service_request__completed_at", date_range)
    failed = _date_filter("service_request__failed_at", date_range)
    # Ledger rows are windowed by the parent terminal timestamp, rather than their
    # creation timestamp, so they match the completed/failed service-hour axes.
    qualifying = (Q(outcome=ServiceRequestConsumption.Outcome.COMPLETED) & completed) | (Q(outcome=ServiceRequestConsumption.Outcome.FAILED) & failed)
    values = ["service_request__assigned_machine_id", "service_request__assigned_machine__name", "service_request__assigned_machine__machine_type__name", "measurement", "product_id", "label"]
    if aggregate:
        values.insert(0, "service_request__makerspace_id")
    rows = ServiceRequestConsumption.objects.filter(
        service_request__makerspace_id__in=ids,
        service_request__assigned_machine__isnull=False,
    ).filter(_request_scope_q(machine_scope, prefix="service_request__")).filter(qualifying).order_by().values(*values).annotate(
        completed_amount=Coalesce(Sum("quantity", filter=Q(outcome=ServiceRequestConsumption.Outcome.COMPLETED) & completed), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))),
        failed_partial_amount=Coalesce(Sum("quantity", filter=Q(outcome=ServiceRequestConsumption.Outcome.FAILED) & failed), Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))),
    )
    return [_record("consumption", row, aggregate) for row in rows]


def _failure_rows(machine_rows, failed_usage, aggregate):
    rows = []
    for machine in machine_rows:
        if not machine["failed_count"]:
            continue
        usage = failed_usage.get((machine.get("makerspace_id"), machine["machine_id"]), {"count": Decimal("0.00"), "grams": Decimal("0.00")})
        row = {
            "row_kind": "failure", "machine_id": machine["machine_id"], "machine_name": machine["machine_name"],
            "machine_type": machine["machine_type"], "outcome": "failed", "failed_count": machine["failed_count"],
            "failed_partial_hours": machine["failed_partial_hours"], "failed_count_amount": usage["count"], "failed_grams_amount": usage["grams"],
        }
        if aggregate:
            row["makerspace_id"] = machine["makerspace_id"]
        rows.append(row)
    return rows


def _failed_usage(rows):
    usage = {}
    for row in rows:
        key = (row.get("makerspace_id"), row["machine_id"])
        item = usage.setdefault(key, {"count": Decimal("0.00"), "grams": Decimal("0.00")})
        item[row["measurement"]] += row["failed_partial_amount"]
    return usage


def _record(kind, row, aggregate):
    makerspace_id = row.get("makerspace_id", row.get("service_request__makerspace_id"))
    if kind == "status":
        record = {"row_kind": kind, **{key: row[key] for key in FIELDS[1:8]}}
    elif kind == "machine":
        completed_hours, failed_hours = _hours(row["completed_minutes"]), _hours(row["failed_minutes"])
        denominator = row["completed_count"] + row["failed_count"]
        record = {"row_kind": kind, "machine_id": row["id"], "machine_name": row["name"], "machine_type": row["machine_type__name"], "request_count": row["requested"], "completed_count": row["completed_count"], "failed_count": row["failed_count"], "completed_hours": completed_hours, "failed_partial_hours": failed_hours, "total_recorded_service_hours": round(completed_hours + failed_hours, 2), "failure_rate": round(row["failed_count"] * 100 / denominator, 2) if denominator else None}
    else:
        completed_amount, failed_amount = _amount(row["completed_amount"]), _amount(row["failed_partial_amount"])
        record = {"row_kind": kind, "machine_id": row["service_request__assigned_machine_id"], "machine_name": row["service_request__assigned_machine__name"], "machine_type": row["service_request__assigned_machine__machine_type__name"], "measurement": row["measurement"], "product_id": row["product_id"], "product_label": row["label"], "completed_amount": completed_amount, "failed_partial_amount": failed_amount, "total_used": _amount(completed_amount + failed_amount)}
    if aggregate:
        record["makerspace_id"] = makerspace_id
    return record


def _date_filter(field, date_range):
    if not date_range:
        return Q()
    start, end = date_range
    query = Q()
    if start is not None:
        query &= Q(**{f"{field}__gte": start})
    if end is not None:
        query &= Q(**{f"{field}__lt": end})
    return query


def _hours(minutes):
    return round(float(minutes or 0) / 60, 2)


def _amount(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _sort_key(row, aggregate):
    prefix = (row["makerspace_id"],) if aggregate else ()
    order = {"status": 0, "machine": 1, "consumption": 2, "failure": 3}
    return (*prefix, order[row["row_kind"]], row.get("machine_name") or "", row.get("machine_id") or 0, row.get("product_label") or "")
