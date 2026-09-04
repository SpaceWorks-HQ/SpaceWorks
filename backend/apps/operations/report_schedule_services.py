"""Run due report schedules: build through the manual export path, store, deliver, record.

Fail-safe per schedule: one broken schedule (bad filters, storage down, a dead webhook)
records a FAILED delivery and lets the sweep carry on. The run is idempotent under a
coarse cron because the claim advances `next_run_at` under a `skip_locked` row lock
BEFORE any work happens; a second worker in the same minute finds nothing due.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts import rbac
from apps.audit import services as audit
from apps.integrations.dispatch import dispatch_email
from apps.integrations.dispatch_destination import deliver_text_to_destination
from apps.integrations.models import EmailLog
from apps.makerspaces.platform import module_enabled
from apps.operations import reports
from apps.operations.models_report_schedules import (
    ReportDelivery,
    ReportSchedule,
    advance_next_run,
)
from apps.operations.report_delivery_storage import (
    delete_report_object,
    report_object_key,
    signed_download_url,
    store_report_object,
)
from apps.operations.report_exports import csv_bytes, xlsx_bytes
from apps.operations.report_exports_provenance import build_provenance, export_filters
from apps.operations.report_registry import REPORT_REGISTRY
from apps.operations.report_scope import eligible_makerspace_ids
from apps.operations.views_report_helpers import date_range_from_dates
from apps.tenant_migration.gate_runtime import fanout_tenant_write

logger = logging.getLogger(__name__)

NOTIFICATION_FEATURE = "reports"
NOTIFICATION_EVENT = "scheduled_report"
PAYMENT_FILTER_KEYS = ("status", "subject_type")


def run_report_schedules(*, now=None, limit=50):
    now = now or timezone.now()
    # Archived, reports-disabled and superadmin-hidden makerspaces never run: the same
    # eligibility the aggregate reports use, applied before any row is claimed.
    due = list(
        ReportSchedule.objects.filter(
            is_active=True, next_run_at__lte=now, makerspace_id__in=eligible_makerspace_ids(),
        ).order_by("next_run_at", "id").values_list("id", "makerspace_id")[: max(int(limit), 1)]
    )
    counts = {"delivered": 0, "failed": 0, "skipped": 0}
    for schedule_id, makerspace_id in due:
        with fanout_tenant_write(
            makerspace_id, operation="report_schedule", counts=counts
        ) as should_process:
            if not should_process:
                continue
            try:
                run_schedule(schedule_id, now=now, counts=counts)
            except Exception:  # noqa: BLE001 - one schedule must never stop the sweep
                logger.exception("report_schedule_run_failed", extra={"schedule_id": schedule_id})
                counts["failed"] += 1
    return counts


def run_schedule(schedule_id, *, now=None, counts=None, force=False, actor=None):
    """Claim and run one schedule. `force` runs it now regardless of `next_run_at`."""
    now = now or timezone.now()
    counts = counts if counts is not None else {"delivered": 0, "failed": 0, "skipped": 0}
    schedule = _claim(schedule_id, now, force)
    if schedule is None:
        return None
    _sweep_expired(schedule, now)
    definition = REPORT_REGISTRY.get(schedule.report_key)
    reason = _skip_reason(schedule, definition)
    if reason:
        audit.record(
            actor, "report_schedule.skipped", makerspace=schedule.makerspace, target=schedule,
            meta={"schedule_id": schedule.pk, "reason": reason},
        )
        counts["skipped"] += 1
        return None
    delivery = _build_and_deliver(schedule, definition, now, actor)
    counts["delivered" if delivery.status == ReportDelivery.Status.SENT else "failed"] += 1
    return delivery


def _claim(schedule_id, now, force):
    with transaction.atomic():
        # `of=("self",)`: the joined creator/destination rows are nullable, and Postgres
        # refuses FOR UPDATE across a nullable outer join unless the lock names one table.
        queryset = (
            ReportSchedule.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("makerspace", "created_by", "destination")
            .filter(pk=schedule_id, is_active=True)
        )
        if not force:
            queryset = queryset.filter(next_run_at__lte=now)
        schedule = queryset.first()
        if schedule is None:
            return None
        if schedule.next_run_at <= now:
            schedule.next_run_at = advance_next_run(schedule.next_run_at, schedule.cadence, now)
        schedule.last_run_at = now
        schedule.save(update_fields=["next_run_at", "last_run_at", "updated_at"])
    return schedule


def _skip_reason(schedule, definition):
    if definition is None or not definition.exportable:
        return "report_unavailable"
    if not module_enabled(schedule.makerspace, "reports"):
        return "module_disabled:reports"
    for module in definition.required_modules:
        if not module_enabled(schedule.makerspace, module):
            return f"module_disabled:{module}"
    creator = schedule.created_by
    if creator is None or not rbac.can(creator, definition.required_action, schedule.makerspace_id):
        return "creator_lacks_action"
    return ""


def schedule_inputs(schedule, now):
    """Translate the stored filters into exactly what the manual export view passes."""
    filters = dict(schedule.filters or {})
    window_days = filters.get("window_days")
    if window_days:
        date_range = (now - timedelta(days=int(window_days)), now)
    else:
        date_range = date_range_from_dates(
            parse_date(filters.get("start") or "") if filters.get("start") else None,
            parse_date(filters.get("end") or "") if filters.get("end") else None,
        )
    report_filters = {}
    if schedule.report_key == "payment-reconciliation":
        report_filters = {key: filters[key] for key in PAYMENT_FILTER_KEYS if filters.get(key)}
    return date_range, report_filters


def _build_and_deliver(schedule, definition, now, actor):
    makerspace = schedule.makerspace
    errors, object_key = [], ""
    try:
        date_range, report_filters = schedule_inputs(schedule, now)
        provenance = build_provenance(
            definition.key, version=definition.version, makerspace_id=makerspace.id,
            generated_by=f"schedule:{schedule.pk}", now=now,
            filters=export_filters(
                date_range=date_range, report_filters=report_filters, grain=schedule.grain,
            ),
        )
        rows = reports.report_rows(
            definition.key, makerspace.id, date_range=date_range,
            report_filters=report_filters, grain=schedule.grain,
        )
        render = xlsx_bytes if schedule.format == ReportSchedule.Format.XLSX else csv_bytes
        payload = render(rows, provenance=provenance)
        key = report_object_key(makerspace.id, definition.key, schedule.format)
        store_report_object(key, payload, schedule.format)
        url = signed_download_url(key)
        object_key = key
    except Exception as exc:  # noqa: BLE001 - recorded on the delivery row instead
        logger.exception("report_schedule_build_failed", extra={"schedule_id": schedule.pk})
        errors.append(f"build:{type(exc).__name__}")
    else:
        errors.extend(_send(schedule, definition, url))
    delivered = not errors
    delivery = ReportDelivery.objects.create(
        schedule=schedule, object_key=object_key,
        status=ReportDelivery.Status.SENT if delivered else ReportDelivery.Status.FAILED,
        error="; ".join(errors)[:2000],
        expires_at=(
            now + timedelta(seconds=settings.REPORT_DELIVERY_URL_TTL_SECONDS) if object_key else None
        ),
    )
    audit.record(
        actor, "report_schedule.delivered" if delivered else "report_schedule.failed",
        makerspace=makerspace, target=schedule,
        meta={"schedule_id": schedule.pk, "delivery_id": delivery.pk},
    )
    return delivery


def _send(schedule, definition, url):
    """Deliver the LINK to every configured leg; the bytes never enter a chat channel."""
    makerspace = schedule.makerspace
    title = definition.title or definition.key
    hours = max(settings.REPORT_DELIVERY_URL_TTL_SECONDS // 3600, 1)
    text = (
        f"Scheduled report '{title}' for {makerspace.name} ({schedule.format.upper()}) is ready. "
        f"Download (link valid about {hours}h): {url}"
    )
    errors = []
    if schedule.destination_id:
        ok, error = deliver_text_to_destination(
            makerspace, schedule.destination, text=text, feature=NOTIFICATION_FEATURE,
            event=NOTIFICATION_EVENT, reference=f"report-schedule-{schedule.pk}",
            payload={"schedule_id": schedule.pk, "report_key": definition.key, "download_url": url},
        )
        if not ok:
            errors.append(f"{schedule.destination.channel}:{error}")
    for email in schedule.recipient_emails or []:
        try:
            log = dispatch_email(
                makerspace=makerspace, to_email=email,
                subject=f"[{makerspace.name}] Scheduled report: {title}", text_body=text,
                stream="reports", event=NOTIFICATION_EVENT, audience="staff", sync=True,
            )
        except Exception as exc:  # noqa: BLE001 - SMTP/fence failures are per-recipient facts
            errors.append(f"email:{type(exc).__name__}")
            continue
        if log.status != EmailLog.Status.SENT:
            # SKIPPED means the `email` module is off for this makerspace; that leg did
            # not deliver, and the row must say so rather than count a silent skip as sent.
            errors.append(f"email:{log.status}")
    if not schedule.destination_id and not schedule.recipient_emails:
        errors.append("no_recipients")
    return errors


def _sweep_expired(schedule, now):
    """Delete this schedule's expired objects; the row keeps the delivery history."""
    for delivery in schedule.deliveries.filter(expires_at__lt=now).exclude(object_key=""):
        delete_report_object(delivery.object_key)
        delivery.object_key = ""
        delivery.save(update_fields=["object_key"])
