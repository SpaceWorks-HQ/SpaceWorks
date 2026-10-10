"""Real enrolled label device and canonical QR batch fixtures for 7c."""
import json
from uuid import uuid4

from django.urls import reverse
from rest_framework.test import APIClient

from apps.boxes.models import QrCode
from apps.devices.models import Device
from apps.devices.principal import DevicePrincipal
from apps.devices.services_label_commands import create_label_command
from apps.operations.models import QrPrintBatch
from apps.operations.services_qr_assets import add_qr_to_batch
from tests.devices.helpers import create_device, device_space, enroll, signed_headers, staff_client
from tests.return_helpers import make_product


def batch_fixture(space, actor, *, title="Bench labels", count=2):
    batch = QrPrintBatch.objects.create(makerspace=space, title=title, created_by=actor)
    for index in range(count):
        product = make_product(space, name=f"Label tool {index}")
        qr = QrCode.objects.create(makerspace=space, target_type="product", target_id=product.pk,
                                   created_by=actor)
        add_qr_to_batch(batch, qr, label_text=product.name)
    return batch


def label_case(slug, *, count=2, sent=False, acknowledged=False):
    space = device_space(slug, modules=("devices", "qr_print_batches"))
    actor, client = staff_client(space, f"{slug}-mgr")
    created = create_device(client, space, kind="label_printer", name="Bench label printer")
    response, private, _public = enroll(created["enrollment"])
    assert response.status_code == 200, response.data
    device = Device.objects.get(pk=created["device"]["id"])
    batch = batch_fixture(space, actor, count=count)
    case = {"space": space, "actor": actor, "client": client, "device": device,
            "private": private, "principal": DevicePrincipal.from_device(device), "batch": batch}
    if sent or acknowledged:
        label, _created = create_label_command(actor, batch.pk, device_id=device.pk, request_id=uuid4())
        case["label"] = label
        if acknowledged:
            from apps.devices.services_commands import acknowledge, lease_command
            lease = lease_command(case["principal"])
            assert lease["label_command_id"] == label.pk
            case["lease"] = lease
            acknowledge(case["principal"], label.command_id, lease["lease_token"])
    return case


def staff_path(case):
    return reverse("devices:admin-label-command-list", args=[case["batch"].pk])


def signed_call(case, name, *, body=None, pk=None, method="POST", device=None):
    device = device or case["device"]
    target = reverse(name, args=[pk or case["label"].pk])
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = signed_headers(device.pk, device.key_version, case["private"],
                             target=target, method=method, body=raw)
    return APIClient().generic(method, target, data=raw, content_type="application/json", **headers)
