"""Service runs contribute actual minutes in addition to independent usage logs."""

from django.db.models import Q
from apps.accounts import rbac
from apps.machines.models import MachineServiceRequest


def runs(machine_id, baseline):
    return MachineServiceRequest.objects.filter(assigned_machine_id=machine_id).filter(
        Q(status__in=("completed", "collected"), completed_at__gte=baseline)
        | Q(status="failed", failed_at__gte=baseline),
    )


def scoped_runs(schedule):
    return rbac.scope_verified_tenant(runs(schedule.machine_id, schedule.meter_started_at),
                                      schedule.machine.makerspace)
