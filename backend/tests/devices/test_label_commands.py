from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.devices.models import Device, LabelPrintCommand
from apps.operations.models import QrPrintBatch
from tests.devices.helpers_labels import batch_fixture, label_case, staff_path
from tests.devices.helpers import create_device, enroll
from tests.handout_roles import make_handout_member
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def send(case, **overrides):
    return case["client"].post(staff_path(case), {"device_id": str(case["device"].pk),
        "request_id": str(uuid4()), **overrides}, format="json")


def test_first_send_freezes_batch_and_matching_replay_creates_no_second_command():
    case = label_case("label-send")
    request_id = str(uuid4())
    first = send(case, request_id=request_id)
    replay = send(case, request_id=request_id)
    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.data["id"] == replay.data["id"]
    case["batch"].refresh_from_db()
    assert case["batch"].status == "printed" and case["batch"].printed_at is not None
    assert LabelPrintCommand.objects.count() == 1
    assert AuditLog.objects.filter(action="qr_print_batch.printed").count() == 1
    assert AuditLog.objects.filter(action="devices.label_command_created", actor=case["actor"]).count() == 1
    assert LabelPrintCommand.objects.get().command.device_key_version == case["device"].key_version


def test_printed_batch_reprint_uses_new_request_id_and_paginated_listing():
    case = label_case("label-reprint", sent=True)
    printed_at = QrPrintBatch.objects.get(pk=case["batch"].pk).printed_at
    assert send(case).status_code == 201
    assert QrPrintBatch.objects.get(pk=case["batch"].pk).printed_at == printed_at
    response = case["client"].get(staff_path(case))
    assert response.status_code == 200 and response.data["count"] == 2
    assert set(response.data) == {"count", "next", "previous", "results"}


@pytest.mark.parametrize("status,count", [("draft", 0), ("printed", 0), ("archived", 2)])
def test_invalid_batch_does_not_queue(status, count):
    case = label_case(f"label-invalid-{status}", count=count)
    QrPrintBatch.objects.filter(pk=case["batch"].pk).update(status=status)
    assert send(case).status_code == 400
    assert not LabelPrintCommand.objects.exists()


@pytest.mark.parametrize("kind,status", [("printer", "active"), ("generic", "active"),
                                        ("label_printer", "pending"), ("label_printer", "revoked")])
def test_device_kind_and_status_are_enforced(kind, status):
    case = label_case(f"label-kind-{kind}-{status}")
    Device.objects.filter(pk=case["device"].pk).update(kind=kind, status=status)
    assert send(case).status_code == 400
    assert not LabelPrintCommand.objects.exists()


def test_request_id_conflict_for_another_batch():
    case = label_case("label-conflict", sent=True)
    request_id = str(case["label"].request_id)
    other = batch_fixture(case["space"], case["actor"])
    case["batch"] = other
    assert send(case, request_id=request_id).status_code == 409
    assert LabelPrintCommand.objects.count() == 1
    other.refresh_from_db()
    assert other.status == "draft"


def test_request_id_conflict_for_another_active_label_device():
    case = label_case("label-device-conflict", sent=True)
    created = create_device(case["client"], case["space"], kind="label_printer", name="Other label printer")
    response, _private, _public = enroll(created["enrollment"])
    assert response.status_code == 200
    assert send(case, request_id=str(case["label"].request_id),
                device_id=created["device"]["id"]).status_code == 409
    assert LabelPrintCommand.objects.count() == 1


def test_manage_qr_without_manage_devices_can_send_but_device_only_role_cannot():
    case = label_case("label-role")
    qr_staff = make_handout_member("label-qr-role", case["space"], actions=(rbac.Action.MANAGE_QR,))
    case["client"] = authenticated_client(qr_staff)
    assert send(case).status_code == 201
    device_staff = make_handout_member("label-device-role", case["space"],
                                      slug="device-only", actions=(rbac.Action.MANAGE_DEVICES,))
    case["client"] = authenticated_client(device_staff)
    assert send(case).status_code in (403, 404)


def test_cross_tenant_device_and_batch_are_not_disclosed():
    case = label_case("label-scope-a")
    other = label_case("label-scope-b")
    assert send(case, device_id=str(other["device"].pk)).status_code == 404
    assert case["client"].get(staff_path(other)).status_code == 404
    assert not LabelPrintCommand.objects.exists()


def test_request_claim_cannot_be_rewritten_by_queryset_update():
    case = label_case("label-claim", sent=True)
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            LabelPrintCommand.objects.filter(pk=case["label"].pk).update(request_id=uuid4())
    case["label"].refresh_from_db()
    assert case["label"].result == "pending"


def test_unknown_fields_are_rejected_at_staff_boundary():
    case = label_case("label-staff-fields")
    assert send(case, object_key="pretend-artifact").status_code == 400


@pytest.mark.parametrize("failure", ["freeze", "provenance"])
def test_first_send_rolls_back_command_and_freeze_on_failure(monkeypatch, failure):
    from apps.devices import services_label_commands as service
    from apps.devices.models import DeviceCommand
    from apps.operations.services_qr_assets import mark_batch_printed

    case = label_case(f"label-create-rollback-{failure}")

    def broken(*args, **kwargs):
        if failure == "freeze":
            mark_batch_printed(*args, **kwargs)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(service, "mark_batch_printed" if failure == "freeze" else "record", broken)
    with pytest.raises(RuntimeError, match="injected failure"):
        service.create_label_command(case["actor"], case["batch"].pk,
            device_id=case["device"].pk, request_id=uuid4())
    case["batch"].refresh_from_db()
    assert case["batch"].status == "draft" and case["batch"].printed_at is None
    assert not LabelPrintCommand.objects.exists() and not DeviceCommand.objects.exists()
    assert not AuditLog.objects.filter(action="qr_print_batch.printed").exists()


def test_batch_claim_cannot_rebind_or_delete_but_requester_fk_may_null():
    case = label_case("label-target-claim", sent=True)
    other = batch_fixture(case["space"], case["actor"])
    for mutation in (
        lambda: LabelPrintCommand.objects.filter(pk=case["label"].pk).update(batch=other),
        lambda: LabelPrintCommand.objects.filter(pk=case["label"].pk).delete(),
    ):
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                mutation()
    # The same SET_NULL update used when deleting a requester remains legal.
    LabelPrintCommand.objects.filter(pk=case["label"].pk).update(requested_by=None)
    case["label"].refresh_from_db()
    assert case["label"].batch_id == case["batch"].pk
    assert case["label"].requested_by_id is None
