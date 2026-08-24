from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.hardware_requests.models import (
    HardwareRequest,
    PublicProblemReport,
    PublicToolLoan,
)
from apps.integrations.models import EmailLog
from apps.inventory.models import InventoryProduct
from apps.makerspaces.platform import module_enabled
from apps.machines import role_scope
from apps.machines.printer_capabilities import PRINTER_SLUG
from apps.operations.models import StocktakeSession
from apps.payments.models import Payment
from apps.warranty.models import Warranty


class DashboardSerializer(serializers.Serializer):
    scope_mode = serializers.ChoiceField(choices=["machine", "full"])
    overdue_loans = serializers.IntegerField(required=False, default=0)
    pending_requests = serializers.IntegerField(required=False, default=0)
    awaiting_issue = serializers.IntegerField(required=False, default=0)
    open_problem_reports = serializers.IntegerField(required=False, default=0)
    low_stock = serializers.IntegerField(required=False, default=0)
    pending_prints = serializers.IntegerField(required=False, default=0)
    active_prints = serializers.IntegerField(required=False, default=0)
    prints_awaiting_collection = serializers.IntegerField(required=False, default=0)
    failed_emails = serializers.IntegerField(required=False, default=0)
    stocktakes_awaiting_approval = serializers.IntegerField(required=False, default=0)
    warranty_expiring = serializers.IntegerField(required=False, default=0)
    maintenance_overdue = serializers.IntegerField(required=False, default=0)
    pending_payments = serializers.IntegerField(required=False, default=0)


def build_dashboard(
    makerspace,
    *,
    machine_scope=role_scope.EXEMPT,
    machine_only=False,
    direct_collect=False,
    include_pending_payments=True,
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
    now = timezone.now()
    today = timezone.localdate()
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

    if not restricted:
        try:
            reviewed_overdue = HardwareRequest.objects.filter(
                makerspace=makerspace,
                status__in=[
                    HardwareRequest.Status.ISSUED,
                    HardwareRequest.Status.PARTIALLY_RETURNED,
                ],
                return_due_at__lt=now,
            ).count()
            direct_overdue = PublicToolLoan.objects.filter(
                makerspace=makerspace,
                returned_at__isnull=True,
                due_at__lt=now,
            ).count()
            counts["overdue_loans"] = reviewed_overdue + direct_overdue
        except Exception:
            pass
        try:
            counts["pending_requests"] = HardwareRequest.objects.filter(
                makerspace=makerspace,
                status=HardwareRequest.Status.PENDING_APPROVAL,
            ).count()
        except Exception:
            pass
        try:
            counts["awaiting_issue"] = HardwareRequest.objects.filter(
                makerspace=makerspace,
                status=HardwareRequest.Status.ACCEPTED,
            ).count()
        except Exception:
            pass
        try:
            counts["open_problem_reports"] = PublicProblemReport.objects.filter(
                makerspace=makerspace,
                resolved_at__isnull=True,
            ).count()
        except Exception:
            pass
        try:
            counts["low_stock"] = InventoryProduct.objects.filter(
                makerspace=makerspace,
                available_quantity=0,
            ).count()
        except Exception:
            pass
    try:
        from apps.machines.models import MachineServiceRequest, MachineType

        printer_type_id = MachineType.objects.filter(
            makerspace__isnull=True, slug=PRINTER_SLUG
        ).values_list("id", flat=True).first()
        if printer_type_id is not None:
            printer_q = Q(pk__in=[])
            for path in role_scope.SERVICE_REQUEST_TYPE_PATHS:
                printer_q |= Q(**{path: printer_type_id})
            printers = MachineServiceRequest.objects.filter(
                makerspace=makerspace
            ).filter(printer_q)
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
    except Exception:
        pass
    if not restricted:
        try:
            counts["failed_emails"] = EmailLog.objects.filter(
                makerspace=makerspace,
                status=EmailLog.Status.FAILED,
                created_at__gte=now - timedelta(days=7),
            ).count()
        except Exception:
            pass
        try:
            counts["stocktakes_awaiting_approval"] = StocktakeSession.objects.filter(
                makerspace=makerspace,
                status=StocktakeSession.Status.COMPLETED,
            ).count()
        except Exception:
            pass
    try:
        warranties = Warranty.objects.filter(
            makerspace=makerspace,
            warranty_expires_on__isnull=False,
            warranty_expires_on__lte=today + timedelta(days=30),
        )
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
    except Exception:
        pass
    if module_enabled(makerspace, "maintenance"):
        try:
            from apps.maintenance.models import MaintenanceSchedule

            schedules = MaintenanceSchedule.objects.filter(
                machine__makerspace=makerspace,
                is_active=True,
                next_due__lt=today,
            )
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
        except Exception:
            pass

    if include_pending_payments and not restricted:
        try:
            counts["pending_payments"] = Payment.objects.filter(
                makerspace=makerspace, status=Payment.Status.PENDING
            ).count()
        except Exception:
            pass
    elif not restricted:
        counts.pop("pending_payments", None)

    return counts
