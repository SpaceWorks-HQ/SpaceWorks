from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts import rbac
from apps.machines import access
from apps.machines.models import Machine
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.maintenance.models import (
    MaintenanceLog,
    MaintenanceLogDocument,
    MaintenanceSchedule,
)


class MaintenancePagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500


def resolve_collection(actor, makerspace_id, machine_id, *, manage=False):
    makerspace = get_object_or_404(
        rbac.scope_by_makerspace(
            actor, Makerspace.objects.all(), makerspace_field="id",
        ),
        pk=makerspace_id,
    )
    machine = get_object_or_404(
        access.scope_machines_for_actor(
            actor,
            Machine.objects.select_related("makerspace", "machine_type"),
        ),
        pk=machine_id,
        makerspace=makerspace,
    )
    require_module(makerspace, "maintenance")
    require_machine_access(actor, machine, manage=manage)
    return machine


def resolve_schedule(actor, pk, *, manage=True):
    machines = access.scope_machines_for_actor(
        actor, Machine.objects.select_related("makerspace", "machine_type"),
    )
    schedule = get_object_or_404(
        MaintenanceSchedule.objects.select_related(
            "machine", "machine__makerspace", "machine__machine_type",
        ).filter(machine__in=machines),
        pk=pk,
    )
    require_module(schedule.machine.makerspace, "maintenance")
    require_machine_access(actor, schedule.machine, manage=manage)
    return schedule


def resolve_log(actor, pk):
    machines = access.scope_machines_for_actor(actor, Machine.objects.all())
    log = get_object_or_404(
        MaintenanceLog.objects.select_related(
            "machine", "machine__makerspace", "machine__machine_type",
        ).filter(machine__in=machines),
        pk=pk,
    )
    require_module(log.machine.makerspace, "maintenance")
    require_machine_access(actor, log.machine, manage=False)
    return log


def resolve_document(actor, pk, *, manage=False):
    machines = access.scope_machines_for_actor(actor, Machine.objects.all())
    document = get_object_or_404(
        MaintenanceLogDocument.objects.select_related(
            "log", "log__machine", "log__machine__makerspace",
            "log__machine__machine_type",
        ).filter(log__machine__in=machines),
        pk=pk,
    )
    require_module(document.log.machine.makerspace, "maintenance")
    require_machine_access(actor, document.log.machine, manage=manage)
    return document


def require_machine_access(actor, machine, *, manage):
    allowed = (
        access.can_manage_machine(actor, machine)
        if manage
        else access.can_operate_machine(actor, machine)
    )
    if not allowed:
        raise PermissionDenied()


def page_response(paginator, page, serializer, *, context=None):
    return Response({
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": serializer(page, many=True, context=context or {}).data,
    })
