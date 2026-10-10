"""Real enrollment and workflow fixtures; no direct authoritative status writes."""
import json
from uuid import uuid4

from rest_framework.test import APIClient

from apps.devices.models import Device
from apps.devices.principal import DevicePrincipal
from apps.devices.services_commands import acknowledge, lease_command
from apps.devices.services_printer_bindings import create_binding
from apps.devices.services_printer_jobs import create_job
from tests.devices.helpers import active_device, signed_headers
from tests.test_machine_service_workflow import in_progress, machine


def printer_case(slug, *, auto=False, leased=False):
    space, actor, client, device_id, private = active_device(slug)
    space.enabled_modules = sorted(set(space.enabled_modules or []) | {"machines", "machine_service"})
    space.save(update_fields=["enabled_modules"])
    device = Device.objects.get(pk=device_id)
    target = machine(space)
    row = in_progress(space, actor=actor, target=target)
    binding = create_binding(actor, space.pk, device_id=device.pk, machine_id=target.pk, auto_apply_terminal=auto)
    job = create_job(actor, space.pk, binding_id=binding.pk, service_request_id=row.pk, external_job_id="job-" + uuid4().hex)
    principal = DevicePrincipal.from_device(device)
    case = {"space": space, "actor": actor, "client": client, "device": device, "private": private,
            "machine": target, "request": row, "binding": binding, "job": job, "principal": principal}
    if leased:
        lease = lease_command(principal)
        acknowledge(principal, job.command_id, lease["lease_token"])
        case["lease"] = lease
    return case


def result_payload(case, **changes):
    return {"operation_id": str(uuid4()), "external_job_id": case["job"].external_job_id,
            "outcome": "completed", "actual_minutes": 15, "consumptions": [], **changes}


def signed_post(case, target, data):
    body = json.dumps(data, separators=(",", ":")).encode()
    headers = signed_headers(case["device"].pk, case["device"].key_version, case["private"], target=target, body=body)
    return APIClient().post(target, body, content_type="application/json", **headers)
