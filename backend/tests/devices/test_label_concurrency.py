import threading
import io
import zipfile
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection

from apps.devices.models import LabelPrintCommand, LabelPrintResult
from apps.devices.services_label_commands import create_label_command
from apps.devices.services_label_results import report_result
from apps.operations.services_qr_assets import add_qr_to_batch
from tests.devices.helpers_labels import label_case

pytestmark = pytest.mark.django_db(transaction=True)


def race(*operations):
    barrier = threading.Barrier(len(operations))
    values, errors = [], []

    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            values.append(operation())
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(operation,)) for operation in operations]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    return values, errors


def test_concurrent_duplicate_staff_request_creates_one_command():
    case = label_case("label-race-create")
    request_id = uuid4()

    def send():
        return create_label_command(case["actor"], case["batch"].pk,
            device_id=case["device"].pk, request_id=request_id)

    values, errors = race(send, send)
    assert not errors and len(values) == 2
    assert len({label.pk for label, _created in values}) == 1
    assert sorted(created for _label, created in values) == [False, True]
    assert LabelPrintCommand.objects.count() == 1


def test_first_send_serializes_against_relabel():
    case = label_case("label-race-freeze")
    item = case["batch"].items.first()
    values, errors = race(
        lambda: create_label_command(case["actor"], case["batch"].pk,
            device_id=case["device"].pk, request_id=uuid4()),
        lambda: add_qr_to_batch(case["batch"], item.qr_code, label_text="New label"),
    )
    assert all(getattr(exc, "status_code", None) == 400 for exc in errors)
    assert LabelPrintCommand.objects.count() == 1
    item.refresh_from_db()
    from apps.devices.services_commands import acknowledge, lease_command
    from apps.devices.services_label_delivery import command_content
    lease = lease_command(case["principal"])
    label = LabelPrintCommand.objects.get()
    acknowledge(case["principal"], label.command_id, lease["lease_token"])
    first, _filename = command_content(case["principal"], label.pk)
    second = command_content(case["principal"], label.pk)[0]
    with zipfile.ZipFile(io.BytesIO(first)) as before, zipfile.ZipFile(io.BytesIO(second)) as after:
        assert {name: before.read(name) for name in before.namelist()} == {
            name: after.read(name) for name in after.namelist()}
    assert item.label_text == ("New label" if not errors else "Label tool 0")


def test_concurrent_same_result_writes_one_receipt_and_one_effect():
    case = label_case("label-race-result", acknowledged=True)
    operation_id = uuid4()

    def result():
        return report_result(case["principal"], case["label"].pk,
            operation_id=operation_id, outcome="retryable_failed", result_code="offline")

    values, errors = race(result, result)
    assert not errors and len({value.pk for value in values}) == 1
    assert LabelPrintResult.objects.count() == 1
    assert LabelPrintCommand.objects.get().command.status == "queued"


def test_send_and_asset_generation_keep_tenant_before_batch_lock_order(monkeypatch):
    from apps.inventory.models import InventoryAsset, TrackingMode
    from apps.makerspaces import limits
    from apps.operations.services_qr_assets import generate_assets_with_qr
    from tests.return_helpers import make_product

    case = label_case("label-race-generate")
    product = make_product(case["space"], name="Missing asset QR", tracking_mode=TrackingMode.INDIVIDUAL,
                           total_quantity=1, available_quantity=1)
    InventoryAsset.objects.create(makerspace=case["space"], product=product, asset_tag="MISSING-QR")
    # Force the managed quota's row lock, even in a self-hosted test configuration.
    monkeypatch.setattr(limits, "resource_limit", lambda _space, _key: 100)
    _values, errors = race(
        lambda: create_label_command(case["actor"], case["batch"].pk,
            device_id=case["device"].pk, request_id=uuid4()),
        lambda: generate_assets_with_qr(case["actor"], product,
            {"count": 1, "print_batch_id": case["batch"].pk}),
    )
    assert all(getattr(exc, "status_code", None) == 400 for exc in errors)
    label = LabelPrintCommand.objects.get()
    assert label.item_count_snapshot in (2, 3)
    assert case["batch"].items.count() == label.item_count_snapshot
