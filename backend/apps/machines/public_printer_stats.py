"""Public, PII-free printer metrics from the machine-service kernel."""

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.inventory.public_image_storage import public_url
from apps.machines.models import MachineServiceRequest, MachineUsageEntry
from apps.machines.printer_capabilities import resolve_global_printer_type

PRINT_STATUS_KEYS = ("pending", "accepted", "printing", "completed", "collected", "failed", "rejected")
COMPLETED = (MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.COLLECTED)


def build_public_printer_stats(makerspace):
    printer_type = resolve_global_printer_type()
    if printer_type is None:
        requests = MachineServiceRequest.objects.none()
        manual = MachineUsageEntry.objects.none()
    else:
        requests = MachineServiceRequest.objects.filter(
            makerspace=makerspace,
            queue__machine_type=printer_type,
        )
        manual = MachineUsageEntry.objects.filter(
            machine__makerspace=makerspace,
            machine__machine_type=printer_type,
            source=MachineUsageEntry.Source.TYPED_MANUAL,
        )
    statuses = {row["status"]: row["count"] for row in requests.values("status").annotate(count=Count("id"))}
    by_machine = {}
    for row in requests.filter(assigned_machine__isnull=False).values("assigned_machine_id", "assigned_machine__name", "run_machine_model", "assigned_machine__image_key").annotate(jobs=Count("id", filter=Q(status__in=COMPLETED)), minutes=Sum("actual_minutes"), grams=Sum("actual_consumed_grams")):
        by_machine[row["assigned_machine_id"]] = {"name": row["assigned_machine__name"], "model": row["run_machine_model"], "jobs": row["jobs"] or 0, "hours": _hours(row["minutes"]), "grams": _number(row["grams"]), "image_url": public_url(row["assigned_machine__image_key"]) or None}
    for row in manual.values("machine_id", "machine__name", "machine__type_payload", "machine__image_key").annotate(hours=Sum("hours"), grams=Sum("consumed_grams")):
        item = by_machine.setdefault(row["machine_id"], {"name": row["machine__name"], "model": (row["machine__type_payload"] or {}).get("model", ""), "jobs": 0, "hours": 0.0, "grams": 0.0, "image_url": public_url(row["machine__image_key"]) or None})
        item["hours"] = round(item["hours"] + float(row["hours"] or 0), 2)
        item["grams"] = round(item["grams"] + _number(row["grams"]), 2)
    per_printer = sorted(by_machine.values(), key=lambda row: (-row["jobs"], -row["grams"], -row["hours"], row["name"]))
    brand_rows = list(requests.filter(actual_consumed_grams__gt=0).values("run_consumable_pool__brand").annotate(grams=Sum("actual_consumed_grams")).order_by("run_consumable_pool__brand"))
    trend = list(requests.filter(actual_consumed_grams__gt=0, completed_at__isnull=False).annotate(period=TruncMonth("completed_at")).values("period").annotate(grams=Sum("actual_consumed_grams")).order_by("period"))
    completed_minutes = sum(requests.filter(status__in=COMPLETED).values_list("actual_minutes", flat=True))
    manual_hours = float(manual.aggregate(total=Sum("hours"))["total"] or 0)
    return {"hours_all_time": round(completed_minutes / 60 + manual_hours, 2), "hours_this_month": _month_hours(requests, manual), "busiest_printer": _busiest(per_printer), "per_printer": per_printer, "grams_all_time": _number(requests.aggregate(total=Sum("actual_consumed_grams"))["total"]) + _number(manual.aggregate(total=Sum("consumed_grams"))["total"]), "by_brand": [{"brand": row["run_consumable_pool__brand"] or "Unbranded", "grams": _number(row["grams"])} for row in brand_rows], "jobs": {"completed": statuses.get(MachineServiceRequest.Status.COMPLETED, 0), "status_counts": {"printing": statuses.get(MachineServiceRequest.Status.IN_PROGRESS, 0), **{key: statuses.get(key, 0) for key in PRINT_STATUS_KEYS if key != "printing"}}, "queue": {"pending": statuses.get("pending", 0), "accepted": statuses.get("accepted", 0), "printing": statuses.get(MachineServiceRequest.Status.IN_PROGRESS, 0)}}, "filament_trend": [{"period": row["period"].strftime("%Y-%m"), "grams": _number(row["grams"])} for row in trend]}


def _month_hours(requests, manual):
    now = timezone.localtime(timezone.now()); start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    minutes = sum(requests.filter(status__in=COMPLETED, completed_at__gte=start).values_list("actual_minutes", flat=True))
    hours = float(manual.filter(created_at__gte=start).aggregate(total=Sum("hours"))["total"] or 0)
    return round(minutes / 60 + hours, 2)


def _busiest(rows):
    if not rows: return None
    row = max(rows, key=lambda item: item["hours"])
    return {"name": row["name"], "model": row["model"], "hours": row["hours"], "completed": row["jobs"], "image_url": row["image_url"]}


def _hours(value): return round(float(value or 0) / 60, 2)
def _number(value): return round(float(value or 0), 2)
