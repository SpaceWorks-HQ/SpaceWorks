import logging
from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from .serializers_dashboard import DashboardSerializer
from .dashboard_programmes import programme_counts
from apps.separability.registry import runtime_active
from apps.accounts import rbac

from apps.hardware_requests.models import (
    PublicProblemReport,
    PublicToolLoan,
)
from apps.integrations.models import EmailLog
from apps.inventory.models import InventoryProduct
from apps.makerspaces.platform import module_enabled, feature_enabled
from apps.makerspaces.local_time import to_local
from apps.machines import role_scope
from apps.machines.printer_capabilities import PRINTER_SLUG
from apps.operations.models import StocktakeSession
from apps.payments.models import Payment
from apps.warranty.models import Warranty

logger = logging.getLogger(__name__)

def build_dashboard(
    makerspace,
    *,
    machine_scope=role_scope.EXEMPT,
    machine_only=False,
    direct_collect=False,
    include_pending_payments=True,
    include_failed_emails=True,
    include_events=True,
    include_bookings=True,
    include_hardware=True,
    include_machines=True,
    actor=None,
):
    """Dashboard counters, narrowed two INDEPENDENT ways.

    ``machine_scope`` narrows the machine-derived counters. ``machine_only`` decides
    whether the non-machine counters appear at all. Conflating the two was wrong: roles
    here are editable and action-based, so a custom role can hold ``VIEW_INVENTORY``
    *and* a scoped ``MANAGE_MACHINES``, and treating "has a machine scope" as "is a
    machine-only actor" silently removed hardware and stock counts that role is
    independently authorized for. Machine scoping must narrow machine data without
    revoking other granted actions.
    """
    from apps.operations import views_dashboard

    def scope(queryset, field="makerspace_id"):
        return rbac.scope_by_makerspace(actor, queryset, makerspace_field=field) if actor is not None else queryset

    now = timezone.now()
    today = to_local(makerspace, now).date()
    scoped = machine_scope is not role_scope.EXEMPT
    restricted = machine_only
    if restricted:
        counts = {
            "scope_mode": "machine",
            "pending_prints": 0,
            "active_prints": 0,
            "prints_awaiting_collection": 0,
            "warranty_expiring": 0,
            "maintenance_overdue": 0,
        }
    else:
        counts = {
            key: 0
            for key in DashboardSerializer().fields
            if key != "scope_mode"
        }
        counts["scope_mode"] = "full"
        counts["outstanding_by_currency"] = {}

    if not restricted and include_hardware and feature_enabled(makerspace, "loans.enabled"):
        try:
            reviewed_overdue = scope(views_dashboard.HardwareRequest.objects.filter(
                makerspace=makerspace,
                status__in=[
                    views_dashboard.HardwareRequest.Status.ISSUED,
                    views_dashboard.HardwareRequest.Status.PARTIALLY_RETURNED,
                ],
                return_due_at__lt=now,
            )).count()
            direct_overdue = scope(PublicToolLoan.objects.filter(
                makerspace=makerspace,
                returned_at__isnull=True,
                due_at__lt=now,
            )).count()
            counts["overdue_loans"] = reviewed_overdue + direct_overdue
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
        try:
            counts["pending_requests"] = scope(views_dashboard.HardwareRequest.objects.filter(
                makerspace=makerspace,
                status=views_dashboard.HardwareRequest.Status.PENDING_APPROVAL,
            )).count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
        try:
            counts["awaiting_issue"] = scope(views_dashboard.HardwareRequest.objects.filter(
                makerspace=makerspace,
                status=views_dashboard.HardwareRequest.Status.ACCEPTED,
            )).count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
        try:
            counts["open_problem_reports"] = scope(PublicProblemReport.objects.filter(
                makerspace=makerspace,
                resolved_at__isnull=True,
            )).count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
        try:
            counts["low_stock"] = scope(InventoryProduct.objects.filter(
                makerspace=makerspace,
                available_quantity=0,
            )).count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    # Print tiles are `printing` data: a space without the module shows zeros, exactly as
    # the maintenance tile below does without `maintenance`.
    if include_machines and module_enabled(makerspace, "printing"):
        try:
            from apps.machines.models import MachineServiceRequest, MachineType

            printer_type_id = MachineType.objects.filter(
                makerspace__isnull=True, slug=PRINTER_SLUG
            ).values_list("id", flat=True).first()
            if printer_type_id is not None:
                printer_q = Q(pk__in=[])
                for path in role_scope.SERVICE_REQUEST_TYPE_PATHS:
                    printer_q |= Q(**{path: printer_type_id})
                printers = scope(MachineServiceRequest.objects.filter(
                    makerspace=makerspace
                )).filter(printer_q)
                prints = printers.filter(
                    role_scope.scope_q_for(
                        machine_scope,
                        machine_id_paths=role_scope.SERVICE_REQUEST_MACHINE_PATHS,
                        type_id_paths=role_scope.SERVICE_REQUEST_TYPE_PATHS,
                    )
                ).distinct()
                counts["pending_prints"] = prints.filter(status=MachineServiceRequest.Status.PENDING).count()
                counts["active_prints"] = prints.filter(status=MachineServiceRequest.Status.IN_PROGRESS).count()
                # Awaiting collection follows COLLECTION authority, which is cumulative and
                # wider than machine scope: a role holding scoped MANAGE_MACHINES plus a
                # DIRECT collect grant can hand over any completed job, so counting only its
                # own machines made the tile disagree with the Handover queue it links to --
                # a job actionable there and invisible here. Built as a separate queryset
                # rather than OR-ing the scope clause, because `scope_q_for` returns an empty
                # `Q()` for an exempt actor and `Q() | X` collapses to `X`.
                awaiting = (printers if direct_collect else prints).filter(
                    status=MachineServiceRequest.Status.COMPLETED
                )
                counts["prints_awaiting_collection"] = awaiting.distinct().count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    if not restricted and include_failed_emails and module_enabled(makerspace, "email"):
        try:
            counts["failed_emails"] = scope(EmailLog.objects.filter(
                makerspace=makerspace,
                status=EmailLog.Status.FAILED,
                created_at__gte=now - timedelta(days=7),
            )).count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    if not restricted and include_hardware and feature_enabled(makerspace, "loans.enabled") and module_enabled(makerspace, "stocktake"):
        try:
            counts["stocktakes_awaiting_approval"] = scope(StocktakeSession.objects.filter(
                makerspace=makerspace,
                status=StocktakeSession.Status.COMPLETED,
            )).count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    try:
        warranties = scope(Warranty.objects.filter(
            makerspace=makerspace,
            warranty_expires_on__isnull=False,
            warranty_expires_on__lte=today + timedelta(days=30),
        ))
        loans_on = not restricted and include_hardware and feature_enabled(makerspace, "loans.enabled")
        machines_on = include_machines and module_enabled(makerspace, "machines")
        warranties = warranties.filter(
            (Q(asset__isnull=False) if loans_on else Q(pk__in=[]))
            | (Q(machine__isnull=False) if machines_on else Q(pk__in=[]))
        )
        if not runtime_active("warranty"):
            warranties = warranties.none()
        if scoped:
            # The team's own machine warranties, plus asset warranties only when the
            # actor holds non-machine authority: an asset warranty is inventory data, so
            # a machine-only maintainer must not see it, while a mixed role already
            # could and machine scoping has nothing to say about assets.
            in_scope_machine = Q(machine__isnull=False) & role_scope.scope_q_for(
                machine_scope,
                machine_id_paths=("machine_id",),
                type_id_paths=("machine__machine_type_id",),
            )
            warranties = warranties.filter(
                in_scope_machine
                if restricted
                else Q(machine__isnull=True) | in_scope_machine
            )
        counts["warranty_expiring"] = warranties.count()
    except Exception as exc:
        logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    if include_machines and module_enabled(makerspace, "maintenance"):
        try:
            from apps.maintenance.models import MaintenanceSchedule

            schedules = scope(MaintenanceSchedule.objects.filter(
                machine__makerspace=makerspace,
                is_active=True,
                next_due__lt=today,
            ), field="machine__makerspace_id")
            # Always scoped: a maintenance schedule names a machine, so there is no
            # non-machine remainder a mixed role could be entitled to.
            if scoped:
                schedules = schedules.filter(
                    role_scope.scope_q_for(
                        machine_scope,
                        machine_id_paths=("machine_id",),
                        type_id_paths=("machine__machine_type_id",),
                    )
                )
            counts["maintenance_overdue"] = schedules.count()
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})

    if include_pending_payments and not restricted:
        try:
            pending = scope(Payment.objects.filter(
                makerspace=makerspace, status=Payment.Status.PENDING
            ))
            counts["pending_payments"] = pending.count()
            # How much, not just how many. Grouped BY CURRENCY and never summed across
            # them: a space taking both INR and USD has two outstanding figures, and one
            # combined number would be meaningless money.
            counts["outstanding_by_currency"] = {
                row["currency"]: str(row["total"])
                for row in pending.values("currency")
                .annotate(total=Sum("amount"))
                .order_by("currency")
            }
        except Exception as exc:
            logger.error("Dashboard aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    elif not restricted:
        counts.pop("pending_payments", None)

    if not restricted:
        try:
            counts.update(programme_counts(makerspace, events=include_events, bookings=include_bookings, actor=actor))
        except Exception as exc:
            logger.error("Dashboard programme aggregation failed", extra={"makerspace_id": makerspace.pk, "error_type": type(exc).__name__})
    return counts
