import io
from datetime import timedelta
from uuid import uuid4
import zipfile

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.devices.models import Device, DeviceEvent, LabelPrintCommand, LabelPrintResult
from apps.devices.models_commands import DeviceCommand
from apps.devices.errors_printers import LeaseExpired, PrinterConflict
from apps.devices.services_commands import acknowledge, lease_command
from apps.devices.services_label_results import report_result
from tests.devices.helpers_labels import label_case, signed_call

pytestmark = pytest.mark.django_db
CONTENT = "devices:device-label-command-content"
RESULT = "devices:device-label-command-result"


def payload(outcome="succeeded", code="ok", operation_id=None):
    return {"operation_id": str(operation_id or uuid4()), "outcome": outcome, "result_code": code}


def test_zip_is_exact_existing_svg_batch_with_safe_private_headers():
    case = label_case("label-zip", acknowledged=True)
    response = signed_call(case, CONTENT, method="GET")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Disposition"] == f'attachment; filename="qr-labels-{case["label"].pk}.zip"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 2
        assert all(name.endswith(".svg") for name in archive.namelist())
        assert all(b"<svg" in archive.read(name) for name in archive.namelist())
    audit = AuditLog.objects.get(action="devices.label_content_downloaded")
    assert audit.actor_id is None
    assert audit.meta["label_command_id"] == str(case["label"].pk)
    assert DeviceEvent.objects.filter(event_type="label_content_downloaded").count() == 1
    encoded = str(audit.meta)
    assert all(item.qr_code.payload not in encoded for item in case["batch"].items.select_related("qr_code"))


def test_unacknowledged_content_result_and_wrong_token_are_refused():
    case = label_case("label-unacked", sent=True)
    lease = lease_command(case["principal"])
    with pytest.raises(PrinterConflict) as exc:
        acknowledge(case["principal"], case["label"].command_id, "wrong" * 10)
    assert getattr(exc.value, "status_code", None) == 409
    assert signed_call(case, CONTENT, method="GET").status_code == 409
    assert signed_call(case, RESULT, body=payload()).status_code == 409
    acknowledge(case["principal"], case["label"].command_id, lease["lease_token"])


def test_acknowledged_long_print_survives_short_delivery_lease_expiry():
    case = label_case("label-long", acknowledged=True)
    DeviceCommand.objects.filter(pk=case["label"].command_id).update(lease_expires_at=timezone.now()-timedelta(hours=1))
    assert signed_call(case, CONTENT, method="GET").status_code == 200
    assert signed_call(case, RESULT, body=payload()).status_code == 200


def test_success_replay_is_identical_and_conflicting_operation_cannot_finish_twice():
    case = label_case("label-success", acknowledged=True)
    body = payload()
    first = signed_call(case, RESULT, body=body)
    replay = signed_call(case, RESULT, body=body)
    assert first.status_code == replay.status_code == 200
    assert first.data == replay.data
    conflict = {**body, "outcome": "failed", "result_code": "printer_error"}
    assert signed_call(case, RESULT, body=conflict).status_code == 409
    assert signed_call(case, RESULT, body=payload()).status_code == 409
    assert LabelPrintResult.objects.count() == 1
    assert AuditLog.objects.filter(action="devices.label_command_succeeded").count() == 1


def test_retry_receipt_replay_does_not_requeue_or_overwrite_a_later_success():
    case = label_case("label-retry", acknowledged=True)
    failure = payload("retryable_failed", "out_of_labels")
    first = signed_call(case, RESULT, body=failure)
    assert first.status_code == 200 and first.data["response_result"] == "retryable_failed"
    command = DeviceCommand.objects.get(pk=case["label"].command_id)
    assert command.status == "queued" and command.lease_token_digest is None
    assert command.acknowledged_at is None and command.next_attempt_at > timezone.now()
    assert lease_command(case["principal"]) is None
    retry = lease_command(case["principal"], now=command.next_attempt_at+timedelta(seconds=1))
    acknowledge(case["principal"], command.pk, retry["lease_token"], now=command.next_attempt_at+timedelta(seconds=1))
    assert signed_call(case, RESULT, body=payload()).status_code == 200
    replay = signed_call(case, RESULT, body=failure)
    assert replay.data == first.data
    case["label"].refresh_from_db()
    assert case["label"].result == "succeeded"
    assert DeviceCommand.objects.get(pk=command.pk).status == "acknowledged"
    assert LabelPrintResult.objects.count() == 2


@pytest.mark.parametrize("outcome", ["failed", "retryable_failed"])
def test_permanent_or_exhausted_failure_is_terminal(settings, outcome):
    settings.DEVICE_COMMAND_MAX_ATTEMPTS = 1
    case = label_case(f"label-exhaust-{outcome}", acknowledged=True)
    first = signed_call(case, RESULT, body=payload(outcome, "printer_error"))
    assert first.status_code == 200 and first.data["response_result"] == "failed"
    assert first.data["response_completed_at"] is not None
    assert DeviceCommand.objects.get(pk=case["label"].command_id).status == "delivery_failed"
    assert lease_command(case["principal"], now=timezone.now()+timedelta(days=1)) is None


def test_late_ack_cannot_cancel_permanent_failure_or_break_result_replay():
    case = label_case("label-late-ack", acknowledged=True)
    body = payload("failed", "printer_error")
    first = signed_call(case, RESULT, body=body)
    with pytest.raises(PrinterConflict) as exc:
        acknowledge(case["principal"], case["label"].command_id, case["lease"]["lease_token"])
    assert getattr(exc.value, "status_code", None) == 409
    assert DeviceCommand.objects.get(pk=case["label"].command_id).status == "delivery_failed"
    assert signed_call(case, RESULT, body=body).data == first.data


def test_key_rotation_cannot_reuse_a_previously_acknowledged_label_command():
    case = label_case("label-rotated", acknowledged=True)
    Device.objects.filter(pk=case["device"].pk).update(key_version=case["device"].key_version+1)
    case["device"].refresh_from_db()
    assert signed_call(case, CONTENT, method="GET").status_code == 403
    assert signed_call(case, RESULT, body=payload()).status_code == 403
    assert not LabelPrintResult.objects.exists()


def test_expired_unacknowledged_lease_requeues_then_exhausts(settings):
    settings.DEVICE_COMMAND_MAX_ATTEMPTS = 1
    case = label_case("label-expire", sent=True)
    lease = lease_command(case["principal"])
    with pytest.raises(LeaseExpired) as exc:
        acknowledge(case["principal"], case["label"].command_id, lease["lease_token"],
                    now=lease["lease_expires_at"]+timedelta(seconds=1))
    assert getattr(exc.value, "status_code", None) == 410
    case["label"].refresh_from_db()
    assert case["label"].result == "failed"
    assert case["label"].command.status == "delivery_failed"


def test_another_signed_device_cannot_fetch_or_report_and_revocation_is_rechecked():
    case = label_case("label-own-a", acknowledged=True)
    other = label_case("label-own-b")
    other["label"] = case["label"]
    assert signed_call(other, CONTENT, method="GET").status_code == 404
    assert signed_call(other, RESULT, body=payload()).status_code == 404
    Device.objects.filter(pk=case["device"].pk).update(status="revoked")
    assert signed_call(case, CONTENT, method="GET").status_code == 401


def test_purged_batch_cancels_delivery_and_snapshots_cannot_restore_it():
    case = label_case("label-purged", sent=True)
    batch_id = case["batch"].pk
    case["batch"].delete()
    assert lease_command(case["principal"]) is None
    case["label"].refresh_from_db()
    assert case["label"].batch_id is None and case["label"].batch_id_snapshot == batch_id
    assert case["label"].command.status == "cancelled" and case["label"].result == "failed"


def test_purged_acknowledged_batch_commits_cancellation_before_410():
    case = label_case("label-content-gone", acknowledged=True)
    case["batch"].delete()
    assert signed_call(case, CONTENT, method="GET").status_code == 410
    assert DeviceCommand.objects.get(pk=case["label"].command_id).status == "cancelled"


def test_result_text_and_unknown_fields_never_enter_receipts_or_logs():
    case = label_case("label-scrub", acknowledged=True)
    assert signed_call(case, RESULT, body={**payload(), "result_message": "secret-token"}).status_code == 400
    assert signed_call(case, RESULT, body=payload("failed", "secret-token")).status_code == 400
    assert not LabelPrintResult.objects.exists()
    assert not AuditLog.objects.filter(meta__icontains="secret-token").exists()


def test_result_receipt_is_database_immutable():
    case = label_case("label-receipt", acknowledged=True)
    receipt = report_result(case["principal"], case["label"].pk, operation_id=uuid4(),
                            outcome="succeeded", result_code="ok")
    for mutation in [lambda: LabelPrintResult.objects.filter(pk=receipt.pk).update(result_code="printer_error"),
                     lambda: LabelPrintResult.objects.filter(pk=receipt.pk).delete()]:
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                mutation()
    assert LabelPrintResult.objects.get(pk=receipt.pk).result_code == "ok"


def test_terminal_label_outcome_is_database_immutable_but_batch_purge_can_null_fk():
    case = label_case("label-terminal-guard", acknowledged=True)
    report_result(case["principal"], case["label"].pk, operation_id=uuid4(),
                  outcome="succeeded", result_code="ok")
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            LabelPrintCommand.objects.filter(pk=case["label"].pk).update(result_code="offline")
    case["batch"].delete()
    case["label"].refresh_from_db()
    assert case["label"].batch_id is None and case["label"].result == "succeeded"


def test_purged_batch_result_commits_cancellation_without_receipt():
    case = label_case("label-result-gone", acknowledged=True)
    case["batch"].delete()
    assert signed_call(case, RESULT, body=payload()).status_code == 410
    assert DeviceCommand.objects.get(pk=case["label"].command_id).status == "cancelled"
    assert not LabelPrintResult.objects.exists()


def test_generic_lease_and_ack_keep_typed_label_provenance():
    case = label_case("label-shared-provenance", acknowledged=True)
    for action in ("command_leased", "command_acknowledged"):
        entry = AuditLog.objects.get(action=f"devices.{action}")
        assert entry.actor_id is None
        assert entry.meta["command_id"] == str(case["label"].command_id)
        assert entry.meta["label_command_id"] == str(case["label"].pk)
        assert entry.meta["qr_batch_id"] == case["batch"].pk
        event = DeviceEvent.objects.get(event_type=action)
        assert event.command_id_snapshot == case["label"].command_id
        assert event.qr_batch_id_snapshot == case["batch"].pk


def test_operation_identity_cannot_be_reused_for_another_label_command():
    from apps.devices.errors_labels import LabelConflict
    from apps.devices.services_label_commands import create_label_command

    case = label_case("label-op-conflict", acknowledged=True)
    operation_id = uuid4()
    report_result(case["principal"], case["label"].pk, operation_id=operation_id,
                  outcome="succeeded", result_code="ok")
    other, _created = create_label_command(case["actor"], case["batch"].pk,
        device_id=case["device"].pk, request_id=uuid4())
    leased = lease_command(case["principal"])
    acknowledge(case["principal"], other.command_id, leased["lease_token"])
    with pytest.raises(LabelConflict):
        report_result(case["principal"], other.pk, operation_id=operation_id,
                      outcome="succeeded", result_code="ok")
    other.refresh_from_db()
    assert other.result == "pending" and LabelPrintResult.objects.count() == 1



def test_result_provenance_failure_rolls_back_receipt_and_retry(monkeypatch):
    from apps.devices import services_label_results as service

    case = label_case("label-result-rollback", acknowledged=True)
    operation_id = uuid4()

    def broken(*args, **kwargs):
        raise RuntimeError("injected provenance failure")

    monkeypatch.setattr(service, "record", broken)
    with pytest.raises(RuntimeError, match="injected provenance failure"):
        service.report_result(case["principal"], case["label"].pk,
            operation_id=operation_id, outcome="retryable_failed", result_code="offline")
    case["label"].refresh_from_db()
    assert case["label"].result == "pending"
    command = DeviceCommand.objects.get(pk=case["label"].command_id)
    assert command.status == "acknowledged" and command.lease_token_digest is not None
    assert not LabelPrintResult.objects.exists()


def test_rotated_device_cannot_replay_a_receipt_from_its_previous_key():
    from rest_framework.exceptions import PermissionDenied
    from apps.devices.principal import DevicePrincipal

    case = label_case("label-replay-rotated", acknowledged=True)
    operation_id = uuid4()
    report_result(case["principal"], case["label"].pk,
                  operation_id=operation_id, outcome="succeeded", result_code="ok")
    Device.objects.filter(pk=case["device"].pk).update(key_version=case["device"].key_version + 1)
    case["device"].refresh_from_db()
    with pytest.raises(PermissionDenied):
        report_result(DevicePrincipal.from_device(case["device"]), case["label"].pk,
                      operation_id=operation_id, outcome="succeeded", result_code="ok")
    assert LabelPrintResult.objects.count() == 1
