"""B7a kernel 3D-printer lifecycle email coverage."""

import pytest
from django.test import override_settings

from apps.integrations.email_templates_registry_defaults import PRINTING_REQUESTER_SUBJECTS
from apps.integrations.models import (
    EmailLog,
    EmailNotificationMute,
    MachineTypeEmailTemplate,
)
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.machines.service_printing_emails import notify_printer_service_status
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def _printer_request(slug):
    makerspace = make_space(slug)
    requester = make_user(f"{slug}-requester")
    requester.email = f"{slug}-requester@example.test"
    requester.save(update_fields=["email"])
    staff = make_user(f"{slug}-staff", access_status="active")
    staff.email = f"{slug}-staff@example.test"
    staff.save(update_fields=["email"])
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=staff, role=MakerspaceMembership.Role.MACHINE_MANAGER,
    )
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    machine = Machine.objects.create(
        makerspace=makerspace, machine_type=printer_type, name="Kernel MK4", type_payload={"model": "MK4"},
    )
    queue = ServiceQueue.objects.create(makerspace=makerspace, machine_type=printer_type, name="Kernel print queue")
    request = MachineServiceRequest.objects.create(
        makerspace=makerspace, queue=queue, requester=requester, assigned_machine=machine,
        requester_name="Private requester", contact_email=requester.email, contact_phone="555-0100",
        title="Kernel bracket", capability_payload={"requested_material": "PLA", "requested_color": "Blue", "quantity": 1},
    )
    return makerspace, request, requester, staff


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_kernel_printer_lifecycle_uses_printing_templates_and_honours_mutes():
    for event in ("accepted", "started", "rejected", "completed"):
        _, request, requester, staff = _printer_request(f"b7a-email-{event}")
        notify_printer_service_status(request, event, sync=True)
        logs = EmailLog.objects.filter(stream="printing", event=event).order_by("audience", "to_email")
        assert {(row.audience, row.to_email) for row in logs} == {
            ("requester", requester.email), ("staff", staff.email),
        }
        assert logs.get(audience="requester").subject == PRINTING_REQUESTER_SUBJECTS[event]
        assert event in logs.get(audience="staff").subject

    makerspace, request, requester, staff = _printer_request("b7a-email-mutes")
    EmailNotificationMute.objects.create(
        makerspace=makerspace, target="requester", stream="printing", event="accepted", audience="requester",
    )
    EmailNotificationMute.objects.create(
        makerspace=makerspace, target=MakerspaceMembership.Role.MACHINE_MANAGER,
        stream="printing", event="started", audience="staff",
    )
    notify_printer_service_status(request, "accepted", sync=True)
    notify_printer_service_status(request, "started", sync=True)
    assert not EmailLog.objects.filter(event="accepted", audience="requester", to_email=requester.email).exists()
    assert EmailLog.objects.filter(event="accepted", audience="staff", to_email=staff.email).exists()
    assert EmailLog.objects.filter(event="started", audience="requester", to_email=requester.email).exists()
    assert not EmailLog.objects.filter(event="started", audience="staff", to_email=staff.email).exists()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_kernel_printer_request_uses_machine_type_printing_override():
    makerspace, request, requester, _staff = _printer_request("b7a-type-override")
    MachineTypeEmailTemplate.objects.create(
        makerspace=makerspace,
        machine_type=request.queue.machine_type,
        stream="printing",
        audience="requester",
        key="accepted",
        subject="TYPE PRINT {{ print_request.id }}",
        text_body="TYPE BODY {{ print_request.title }}",
    )

    notify_printer_service_status(request, "accepted", sync=True)

    row = EmailLog.objects.get(event="accepted", audience="requester", to_email=requester.email)
    assert row.subject == f"TYPE PRINT {request.pk}"
    assert row.text_body == "TYPE BODY Kernel bracket"
