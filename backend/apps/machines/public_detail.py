"""Safe derived disclosures. Aggregate service estimates never carry requester data."""

import math
from django.db.models import Q
from django.utils import timezone

from apps.accounts import rbac
from apps.makerspaces.platform import module_enabled, feature_enabled
from .models import Machine, MachineServiceRequest, CertificationType


def training(machine):
    if "training" not in machine.public_fields:
        return None
    if not feature_enabled(machine.makerspace, "machines.certifications"):
        return False
    return rbac.scope_public_catalogue(CertificationType.objects.all(), machine.makerspace).filter(
        machine_type_id=machine.machine_type_id, is_active=True, is_required_for_service=True,
    ).exists()


def queue_estimate(machine):
    if "queue_eta" not in machine.public_fields or not module_enabled(machine.makerspace, "machine_service"):
        return None
    rows = rbac.scope_public_catalogue(MachineServiceRequest.objects.all(), machine.makerspace).filter(
        Q(bucket__machine=machine) | Q(queue__machine_type_id=machine.machine_type_id),
        status__in=(MachineServiceRequest.Status.ACCEPTED, MachineServiceRequest.Status.IN_PROGRESS),
    )
    jobs = list(rows.values("estimated_minutes", "started_at", "status"))
    minutes = 0
    unknown = False
    for job in jobs:
        estimate = job["estimated_minutes"]
        if not estimate:
            unknown = True
            continue
        if job["status"] == MachineServiceRequest.Status.IN_PROGRESS and job["started_at"]:
            estimate = max(0, estimate - (timezone.now()-job["started_at"]).total_seconds()/60)
        minutes += estimate
    parallel = rbac.scope_public_catalogue(Machine.objects.all(), machine.makerspace).filter(
        machine_type_id=machine.machine_type_id, is_active=True,
        status__in=(Machine.Status.IDLE, Machine.Status.RUNNING),
    ).count()
    return {"length": len(jobs), "eta_minutes": None if unknown or not parallel else math.ceil(minutes/parallel)}
