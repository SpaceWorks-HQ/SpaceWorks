from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import InventoryAsset
from apps.machines.models import Machine, MachineOperator, MachineType
from apps.makerspaces.models import MakerspaceMembership
from apps.warranty.models import Warranty, WarrantyDocument
from apps.warranty.status import warranty_status
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def enable_modules(makerspace, *modules):
    enabled = set(makerspace.enabled_modules or [])
    enabled.update(modules)
    makerspace.enabled_modules = sorted(enabled)
    makerspace.save(update_fields=["enabled_modules"])


def make_asset(makerspace, *, tag="A-1", serial="SN1"):
    return InventoryAsset.objects.create(
        makerspace=makerspace,
        product=make_product(makerspace),
        asset_tag=tag,
        serial_number=serial,
    )


def make_printer(makerspace, *, name="Printer 1", model="Ender 3"):
    return make_machine(makerspace, name=name)

def make_machine(makerspace, *, name="Machine 1", machine_type=None):
    enable_modules(makerspace, "machines")
    machine_type = machine_type or MachineType.objects.get(
        makerspace__isnull=True,
        slug="3d_printer",
    )
    return Machine.objects.create(
        makerspace=makerspace,
        machine_type=machine_type,
        name=name,
    )


def attach_asset_warranty(asset, **overrides):
    defaults = {
        "makerspace": asset.makerspace,
        "asset": asset,
        "purchased_on": timezone.localdate() - timedelta(days=90),
        "warranty_expires_on": timezone.localdate() + timedelta(days=90),
        "vendor_name": "Warranty Vendor Asset",
        "vendor_contact": "asset@example.com",
    }
    defaults.update(overrides)
    return Warranty.objects.create(**defaults)


def attach_printer_warranty(printer, **overrides):
    defaults = {
        "makerspace": printer.makerspace,
        "machine": printer,
        "purchased_on": timezone.localdate() - timedelta(days=90),
        "warranty_expires_on": timezone.localdate() + timedelta(days=90),
        "vendor_name": "Warranty Vendor Printer",
        "vendor_contact": "printer@example.com",
    }
    defaults.update(overrides)
    return Warranty.objects.create(**defaults)

def attach_machine_warranty(machine, **overrides):
    defaults = {
        "makerspace": machine.makerspace,
        "machine": machine,
        "purchased_on": timezone.localdate() - timedelta(days=90),
        "warranty_expires_on": timezone.localdate() + timedelta(days=90),
        "vendor_name": "Warranty Vendor Machine",
        "vendor_contact": "machine@example.com",
    }
    defaults.update(overrides)
    return Warranty.objects.create(**defaults)


def warranty_payload(**overrides):
    today = timezone.localdate()
    payload = {
        "purchased_on": str(today - timedelta(days=120)),
        "warranty_expires_on": str(today + timedelta(days=45)),
        "vendor_name": "Warranty Vendor One",
        "vendor_contact": "support@example.com",
    }
    payload.update(overrides)
    return payload


def mock_warranty_storage(monkeypatch, *, size=123, content_type="application/pdf"):
    monkeypatch.setattr(
        "apps.warranty.storage.presigned_upload",
        lambda object_key, content_type: {
            "url": "http://minio/warranty",
            "fields": {"key": object_key, "Content-Type": content_type},
        },
    )
    monkeypatch.setattr("apps.warranty.storage.finalize_upload", lambda object_key, max_bytes: size)
    monkeypatch.setattr(
        "apps.warranty.storage.validate_warranty_object",
        lambda object_key: SimpleNamespace(size=size, content_type=content_type),
    )
    monkeypatch.setattr("apps.warranty.storage.presigned_get_url", lambda object_key: "https://signed")
    delete = Mock()
    monkeypatch.setattr("apps.warranty.storage.delete_object", delete)
    return delete


def response_rows(response):
    return response.data["results"] if isinstance(response.data, dict) and "results" in response.data else response.data


def contains_key(value, key):
    if isinstance(value, dict):
        return key in value or any(contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(contains_key(child, key) for child in value)
    return False


def assert_no_public_warranty_leak(response, *sentinels):
    # The vendor-name + date sentinels are the real leak guard (they are the actual
    # warranty payload values). A blanket substring check on "warranty" is unreliable
    # because a fixture's own makerspace name/slug legitimately contains the word, so we
    # assert on the warranty-specific field NAMES instead.
    text = response.content.decode("utf-8")
    for sentinel in sentinels:
        assert sentinel not in text
    if hasattr(response, "data"):
        for key in ("warranty", "vendor_name", "vendor_contact", "warranty_expires_on", "purchased_on"):
            assert not contains_key(response.data, key)


def test_asset_warranty_upsert_read_update_and_audit():
    makerspace = make_space("warranty-asset-upsert")
    user = make_member("warranty-asset-manager", makerspace)
    asset = make_asset(makerspace)
    client = authenticated_client(user)
    url = reverse("admin-asset-warranty", kwargs={"pk": asset.id})

    created = client.put(url, warranty_payload(), format="json")
    read = client.get(url)
    updated = client.put(
        url,
        warranty_payload(
            warranty_expires_on=str(timezone.localdate() + timedelta(days=15)),
            vendor_name="Warranty Vendor Updated",
        ),
        format="json",
    )

    assert created.status_code == 200
    assert read.status_code == 200
    assert read.data["host_kind"] == "asset"
    assert read.data["asset_id"] == asset.id
    assert read.data["purchased_on"] == warranty_payload()["purchased_on"]
    assert read.data["warranty_expires_on"] == warranty_payload()["warranty_expires_on"]
    assert read.data["vendor_name"] == "Warranty Vendor One"
    assert read.data["vendor_contact"] == "support@example.com"
    assert read.data["status"] == "active"
    assert updated.status_code == 200
    assert updated.data["vendor_name"] == "Warranty Vendor Updated"
    assert updated.data["status"] == "expiring_soon"
    assert list(AuditLog.objects.order_by("id").values_list("action", flat=True)) == [
        "warranty.created",
        "warranty.updated",
    ]


def test_printer_warranty_upsert_read_update_and_audit():
    makerspace = make_space("warranty-printer-upsert")
    user = make_member("warranty-printer-manager", makerspace)
    printer = make_printer(makerspace)
    client = authenticated_client(user)
    url = reverse("admin-machine-warranty", kwargs={"pk": printer.id})

    created = client.put(url, warranty_payload(vendor_name="Printer Warranty Vendor"), format="json")
    read = client.get(url)
    updated = client.put(
        url,
        warranty_payload(
            warranty_expires_on=str(timezone.localdate() + timedelta(days=15)),
            vendor_name="Printer Warranty Updated",
        ),
        format="json",
    )

    assert created.status_code == 200
    assert read.status_code == 200
    assert read.data["host_kind"] == "machine"
    assert read.data["machine_id"] == printer.id
    assert read.data["machine_name"] == "Printer 1"
    assert read.data["vendor_name"] == "Printer Warranty Vendor"
    assert read.data["status"] == "active"
    assert updated.status_code == 200
    assert updated.data["vendor_name"] == "Printer Warranty Updated"
    assert updated.data["status"] == "expiring_soon"
    assert list(AuditLog.objects.order_by("id").values_list("action", flat=True)) == [
        "warranty.created",
        "warranty.updated",
    ]


def test_machine_warranty_upsert_and_generic_document_endpoints(monkeypatch):
    delete = mock_warranty_storage(monkeypatch)
    makerspace = make_space("warranty-machine-upsert")
    user = make_member("warranty-machine-manager", makerspace)
    machine = make_machine(makerspace, name="CNC Router")
    client = authenticated_client(user)
    url = reverse("admin-machine-warranty", kwargs={"pk": machine.id})

    created = client.put(
        url,
        warranty_payload(vendor_name="Machine Warranty Vendor"),
        format="json",
    )
    read = client.get(url)
    updated = client.put(
        url,
        warranty_payload(
            warranty_expires_on=str(timezone.localdate() + timedelta(days=15)),
            vendor_name="Machine Warranty Updated",
        ),
        format="json",
    )
    warranty = Warranty.objects.get(machine=machine)
    presign = client.post(
        reverse("admin-warranty-document-presign", kwargs={"pk": warranty.id}),
        {"filename": "machine-bill.pdf", "content_type": "application/pdf"},
        format="json",
    )
    finalized = client.post(
        reverse("admin-warranty-documents", kwargs={"pk": warranty.id}),
        {
            "object_key": presign.data["object_key"],
            "original_filename": "machine-bill.pdf",
        },
        format="json",
    )
    document = WarrantyDocument.objects.get(warranty=warranty)
    listed = client.get(
        reverse("admin-warranty-documents", kwargs={"pk": warranty.id})
    )
    signed = client.get(
        reverse("admin-warranty-document-url", kwargs={"pk": document.id})
    )
    deleted = client.delete(
        reverse("admin-warranty-document-detail", kwargs={"pk": document.id})
    )

    assert created.status_code == 200
    assert read.status_code == 200
    assert read.data["host_kind"] == "machine"
    assert read.data["host_id"] == machine.id
    assert read.data["host_label"] == "CNC Router"
    assert read.data["machine_id"] == machine.id
    assert read.data["machine_name"] == "CNC Router"
    assert read.data["asset_id"] is None
    assert updated.status_code == 200
    assert updated.data["vendor_name"] == "Machine Warranty Updated"
    assert updated.data["status"] == "expiring_soon"
    assert warranty.makerspace_id == machine.makerspace_id
    assert presign.status_code == 201
    assert finalized.status_code == 201
    assert listed.status_code == 200
    assert [row["id"] for row in listed.data] == [document.id]
    assert signed.data == {"url": "https://signed"}
    assert deleted.status_code == 204
    delete.assert_called_once_with(document.object_key)
    assert list(AuditLog.objects.order_by("id").values_list("action", flat=True)) == [
        "warranty.created",
        "warranty.updated",
        "warranty.document_added",
        "warranty.document_removed",
    ]


def test_warranty_rbac_status_code_contract():
    makerspace = make_space("warranty-rbac")
    other_space = make_space("warranty-rbac-other")
    asset = make_asset(makerspace)
    printer = make_printer(makerspace)
    inventory_manager = make_member(
        "warranty-rbac-inventory",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    print_manager = make_member(
        "warranty-rbac-print",
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    guest_admin = make_handout_member("warranty-rbac-guest", makerspace)
    space_manager = make_member("warranty-rbac-space-manager", makerspace)
    other_member = make_member("warranty-rbac-other-user", other_space)

    asset_url = reverse("admin-asset-warranty", kwargs={"pk": asset.id})
    printer_url = reverse("admin-machine-warranty", kwargs={"pk": printer.id})

    assert authenticated_client(inventory_manager).put(printer_url, warranty_payload(), format="json").status_code == 403
    assert authenticated_client(print_manager).put(asset_url, warranty_payload(), format="json").status_code == 403
    assert authenticated_client(guest_admin).put(asset_url, warranty_payload(), format="json").status_code == 403
    assert authenticated_client(guest_admin).put(printer_url, warranty_payload(), format="json").status_code == 403
    assert authenticated_client(other_member).put(asset_url, warranty_payload(), format="json").status_code == 404
    assert authenticated_client(other_member).put(printer_url, warranty_payload(), format="json").status_code == 404
    assert authenticated_client(space_manager).put(asset_url, warranty_payload(), format="json").status_code == 200
    assert authenticated_client(space_manager).put(printer_url, warranty_payload(), format="json").status_code == 200


def test_machine_warranty_operator_type_manager_tenant_and_module_contract():
    makerspace = make_space("warranty-machine-rbac")
    other_space = make_space("warranty-machine-rbac-other")
    machine = make_machine(makerspace, name="Operator Machine")
    type_machine = make_machine(makerspace, name="Type Managed Machine")
    custom_type = MachineType.objects.create(
        makerspace=makerspace,
        slug="custom-cnc",
        name="Custom CNC",
    )
    custom_machine = make_machine(
        makerspace,
        name="Custom Machine",
        machine_type=custom_type,
    )
    manage = make_handout_member("warranty-machine-manage", makerspace)
    full = make_handout_member("warranty-machine-full", makerspace)
    operate = make_handout_member("warranty-machine-operate", makerspace)
    type_manager = make_member(
        "warranty-machine-type-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    other_member = make_member("warranty-machine-other", other_space)
    MachineOperator.objects.bulk_create(
        [
            MachineOperator(
                machine=machine,
                user=manage,
                access_level=MachineOperator.AccessLevel.MANAGE,
            ),
            MachineOperator(
                machine=machine,
                user=full,
                access_level=MachineOperator.AccessLevel.FULL,
            ),
            MachineOperator(
                machine=machine,
                user=operate,
                access_level=MachineOperator.AccessLevel.OPERATE,
            ),
        ]
    )
    url = reverse("admin-machine-warranty", kwargs={"pk": machine.id})
    type_url = reverse("admin-machine-warranty", kwargs={"pk": type_machine.id})
    custom_url = reverse("admin-machine-warranty", kwargs={"pk": custom_machine.id})

    assert authenticated_client(manage).put(url, warranty_payload(), format="json").status_code == 200
    assert authenticated_client(full).get(url).status_code == 200
    assert authenticated_client(operate).get(url).status_code == 403
    assert authenticated_client(type_manager).put(
        type_url, warranty_payload(), format="json"
    ).status_code == 200
    assert authenticated_client(type_manager).put(
        custom_url, warranty_payload(), format="json"
    ).status_code == 403
    assert authenticated_client(other_member).get(url).status_code == 404

    warranty = Warranty.objects.get(machine=machine)
    assert authenticated_client(operate).post(
        reverse("admin-warranty-document-presign", kwargs={"pk": warranty.id}),
        {"filename": "denied.pdf", "content_type": "application/pdf"},
        format="json",
    ).status_code == 403

    makerspace.enabled_modules = [
        module for module in makerspace.enabled_modules if module != "machines"
    ]
    makerspace.save(update_fields=["enabled_modules"])
    assert authenticated_client(manage).get(url).status_code == 400
    assert authenticated_client(operate).get(url).status_code == 403


def test_warranty_documents_presign_finalize_url_delete_and_guards(monkeypatch):
    delete = mock_warranty_storage(monkeypatch)
    makerspace = make_space("warranty-docs")
    other_space = make_space("warranty-docs-other")
    asset = make_asset(makerspace)
    warranty = attach_asset_warranty(asset)
    space_manager = make_member("warranty-docs-manager", makerspace)
    print_manager = make_member(
        "warranty-docs-print",
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    other_member = make_member("warranty-docs-other-user", other_space)
    client = authenticated_client(space_manager)

    presign = client.post(
        reverse("admin-warranty-document-presign", kwargs={"pk": warranty.id}),
        {"filename": "bill.pdf", "content_type": "application/pdf"},
        format="json",
    )
    object_key = presign.data["object_key"]
    finalized = client.post(
        reverse("admin-warranty-documents", kwargs={"pk": warranty.id}),
        {"object_key": object_key, "original_filename": "bill.pdf"},
        format="json",
    )
    document = WarrantyDocument.objects.get()
    url_response = client.get(reverse("admin-warranty-document-url", kwargs={"pk": document.id}))
    duplicate = client.post(
        reverse("admin-warranty-documents", kwargs={"pk": warranty.id}),
        {"object_key": object_key, "original_filename": "bill-again.pdf"},
        format="json",
    )
    wrong_prefix = client.post(
        reverse("admin-warranty-documents", kwargs={"pk": warranty.id}),
        {
            "object_key": f"warranty/{other_space.id}/foreign.pdf",
            "original_filename": "foreign.pdf",
        },
        format="json",
    )
    print_denied = authenticated_client(print_manager).post(
        reverse("admin-warranty-documents", kwargs={"pk": warranty.id}),
        {
            "object_key": f"warranty/{makerspace.id}/print-denied.pdf",
            "original_filename": "print-denied.pdf",
        },
        format="json",
    )
    cross_tenant = authenticated_client(other_member).get(
        reverse("admin-warranty-document-url", kwargs={"pk": document.id})
    )
    deleted = client.delete(reverse("admin-warranty-document-detail", kwargs={"pk": document.id}))

    assert presign.status_code == 201
    assert object_key.startswith(f"warranty/{makerspace.id}/")
    assert presign.data["upload"]["url"] == "http://minio/warranty"
    assert finalized.status_code == 201
    assert finalized.data["content_type"] == "application/pdf"
    assert finalized.data["size_bytes"] == 123
    assert "object_key" not in finalized.data
    assert document.object_key == object_key
    assert url_response.status_code == 200
    assert url_response.data == {"url": "https://signed"}
    assert duplicate.status_code == 400
    assert wrong_prefix.status_code == 400
    assert print_denied.status_code == 403
    assert cross_tenant.status_code == 404
    assert deleted.status_code == 204
    assert not WarrantyDocument.objects.filter(pk=document.pk).exists()
    delete.assert_called_once_with(object_key)
    assert list(AuditLog.objects.order_by("id").values_list("action", flat=True)) == [
        "warranty.document_added",
        "warranty.document_removed",
    ]


def test_validate_warranty_object_sniffs_pdf_and_rejects_html(monkeypatch):
    from apps.warranty import storage

    class FakeBody:
        def __init__(self, data):
            self.data = data

        def read(self, _size):
            return self.data

    class FakeWarrantyClient:
        data = b"%PDF-1.5 warranty document"

        def get_object(self, Bucket, Key):
            return {"Body": FakeBody(self.data)}

    fake_client = FakeWarrantyClient()
    monkeypatch.setattr("apps.warranty.storage._client", lambda: fake_client)
    monkeypatch.setattr("apps.warranty.storage.object_size", lambda object_key: 123)

    result = storage.validate_warranty_object("warranty/1/doc.pdf")
    fake_client.data = b"<html>not a bill</html>"

    assert result.content_type == "application/pdf"
    with pytest.raises(ValidationError):
        storage.validate_warranty_object("warranty/1/doc.pdf")


def test_warranty_status_computation_boundaries():
    today = timezone.localdate()

    assert warranty_status(SimpleNamespace(warranty_expires_on=None), today) == "unknown"
    assert warranty_status(SimpleNamespace(warranty_expires_on=today - timedelta(days=1)), today) == "expired"
    assert warranty_status(SimpleNamespace(warranty_expires_on=today + timedelta(days=15)), today) == "expiring_soon"
    assert warranty_status(SimpleNamespace(warranty_expires_on=today + timedelta(days=30)), today) == "expiring_soon"
    assert warranty_status(SimpleNamespace(warranty_expires_on=today + timedelta(days=31)), today) == "active"


def test_warranty_model_constraints_enforce_exactly_one_of_asset_or_machine_host():
    makerspace = make_space("warranty-constraints")
    asset = make_asset(makerspace)
    machine = make_machine(makerspace)

    with pytest.raises(IntegrityError), transaction.atomic():
        Warranty.objects.create(makerspace=makerspace)
    with pytest.raises(IntegrityError), transaction.atomic():
        Warranty.objects.create(makerspace=makerspace, asset=asset, machine=machine)

def test_warranty_data_does_not_leak_to_public_payloads():
    makerspace = make_space("warranty-public-leak")
    enable_modules(makerspace, "public_inventory", "machine_service")
    makerspace.public_stats_enabled = True
    makerspace.save(update_fields=["public_stats_enabled"])
    product = make_product(makerspace, name="Public Laser")
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag="LEAK-A-1",
        serial_number="LEAK-SN-1",
    )
    printer = make_printer(makerspace, name="Stats Printer", model="Visible Model")
    asset_warranty = attach_asset_warranty(
        asset,
        purchased_on=timezone.datetime(2026, 1, 2).date(),
        warranty_expires_on=timezone.datetime(2027, 3, 4).date(),
        vendor_name="NEVER_PUBLIC_ASSET_VENDOR",
    )
    printer_warranty = attach_printer_warranty(
        printer,
        purchased_on=timezone.datetime(2026, 2, 3).date(),
        warranty_expires_on=timezone.datetime(2027, 4, 5).date(),
        vendor_name="NEVER_PUBLIC_PRINTER_VENDOR",
    )
    machine = make_machine(makerspace, name="Private Warranty Machine")
    machine_warranty = attach_machine_warranty(
        machine,
        purchased_on=timezone.datetime(2026, 3, 4).date(),
        warranty_expires_on=timezone.datetime(2027, 5, 6).date(),
        vendor_name="NEVER_PUBLIC_MACHINE_VENDOR",
        vendor_contact="NEVER_PUBLIC_MACHINE_CONTACT",
    )
    WarrantyDocument.objects.create(
        warranty=asset_warranty,
        object_key=f"warranty/{makerspace.id}/asset.pdf",
        original_filename="asset.pdf",
        content_type="application/pdf",
        size_bytes=123,
    )
    WarrantyDocument.objects.create(
        warranty=printer_warranty,
        object_key=f"warranty/{makerspace.id}/printer.pdf",
        original_filename="printer.pdf",
        content_type="application/pdf",
        size_bytes=123,
    )
    WarrantyDocument.objects.create(
        warranty=machine_warranty,
        object_key=f"warranty/{makerspace.id}/machine.pdf",
        original_filename="NEVER_PUBLIC_MACHINE_BILL.pdf",
        content_type="application/pdf",
        size_bytes=123,
    )

    client = APIClient()
    responses = [
        client.get(reverse("public-inventory", kwargs={"makerspace_slug": makerspace.slug})),
        client.get(reverse("public-inventory-detail", kwargs={"makerspace_slug": makerspace.slug, "pk": product.id})),
        client.get(f"/api/v1/bootstrap?slug={makerspace.slug}"),
        client.get(reverse("public-makerspace-stats", kwargs={"makerspace_slug": makerspace.slug})),
    ]

    for response in responses:
        assert response.status_code == 200
        assert_no_public_warranty_leak(
            response,
            "NEVER_PUBLIC_ASSET_VENDOR",
            "NEVER_PUBLIC_PRINTER_VENDOR",
            "NEVER_PUBLIC_MACHINE_VENDOR",
            "NEVER_PUBLIC_MACHINE_CONTACT",
            "NEVER_PUBLIC_MACHINE_BILL.pdf",
            "2026-01-02",
            "2027-03-04",
            "2026-02-03",
            "2027-04-05",
            "2026-03-04",
            "2027-05-06",
        )


def test_warranty_report_gates_rows_by_host_action_and_makerspace_scope():
    makerspace = make_space("warranty-report")
    other_space = make_space("warranty-report-other")
    covered_asset = make_asset(makerspace, tag="A-COVERED")
    uncovered_asset = make_asset(makerspace, tag="A-UNCOVERED")
    covered_printer = make_printer(makerspace, name="Printer Covered")
    uncovered_printer = make_printer(makerspace, name="Printer Uncovered")
    asset_warranty = attach_asset_warranty(covered_asset, vendor_name="Asset Report Vendor")
    printer_warranty = attach_printer_warranty(covered_printer, vendor_name="Printer Report Vendor")
    guest_admin = make_handout_member("warranty-report-guest", makerspace)
    inventory_manager = make_member(
        "warranty-report-inventory",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    print_manager = make_member(
        "warranty-report-print",
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    space_manager = make_member("warranty-report-space-manager", makerspace)
    url = reverse("admin-makerspace-warranties", kwargs={"makerspace_id": makerspace.id})
    other_url = reverse("admin-makerspace-warranties", kwargs={"makerspace_id": other_space.id})

    guest = authenticated_client(guest_admin).get(url)
    inventory = authenticated_client(inventory_manager).get(url)
    printing = authenticated_client(print_manager).get(url)
    space = authenticated_client(space_manager).get(url)
    cross_tenant = authenticated_client(space_manager).get(other_url)

    assert guest.status_code == 200
    assert response_rows(guest) == []
    assert inventory.status_code == 200
    inventory_rows = response_rows(inventory)
    assert [row["host_kind"] for row in inventory_rows] == ["asset", "asset"]
    assert {row["host_id"] for row in inventory_rows} == {covered_asset.id, uncovered_asset.id}
    covered_asset_row = next(row for row in inventory_rows if row["host_id"] == covered_asset.id)
    uncovered_asset_row = next(row for row in inventory_rows if row["host_id"] == uncovered_asset.id)
    assert covered_asset_row["vendor_name"] == asset_warranty.vendor_name
    assert covered_asset_row["status"] == "active"
    assert uncovered_asset_row["vendor_name"] is None
    assert uncovered_asset_row["warranty_expires_on"] is None
    assert uncovered_asset_row["status"] == "unknown"
    assert printing.status_code == 200
    printing_rows = response_rows(printing)
    assert [row["host_kind"] for row in printing_rows] == ["machine", "machine"]
    assert {row["host_id"] for row in printing_rows} == {covered_printer.id, uncovered_printer.id}
    covered_printer_row = next(row for row in printing_rows if row["host_id"] == covered_printer.id)
    uncovered_printer_row = next(row for row in printing_rows if row["host_id"] == uncovered_printer.id)
    assert covered_printer_row["vendor_name"] == printer_warranty.vendor_name
    assert covered_printer_row["status"] == "active"
    assert uncovered_printer_row["vendor_name"] is None
    assert uncovered_printer_row["warranty_expires_on"] is None
    assert uncovered_printer_row["status"] == "unknown"
    assert space.status_code == 200
    assert [row["host_kind"] for row in response_rows(space)] == [
        "asset",
        "asset",
        "machine",
        "machine",
    ]
    assert cross_tenant.status_code == 404


def test_warranty_report_machine_rows_include_manage_and_full_not_operate():
    makerspace = make_space("warranty-report-machine-tiers")
    actor = make_handout_member("warranty-report-machine-operator", makerspace)
    manage_machine = make_machine(makerspace, name="Manage Machine")
    full_machine = make_machine(makerspace, name="Full Machine")
    operate_machine = make_machine(makerspace, name="Operate Machine")
    for machine, level in (
        (manage_machine, MachineOperator.AccessLevel.MANAGE),
        (full_machine, MachineOperator.AccessLevel.FULL),
        (operate_machine, MachineOperator.AccessLevel.OPERATE),
    ):
        MachineOperator.objects.create(
            machine=machine,
            user=actor,
            access_level=level,
        )
        attach_machine_warranty(machine)

    response = authenticated_client(actor).get(
        reverse(
            "admin-makerspace-warranties",
            kwargs={"makerspace_id": makerspace.id},
        )
    )

    assert response.status_code == 200
    assert response.data["count"] == 2
    assert [row["host_kind"] for row in response_rows(response)] == [
        "machine",
        "machine",
    ]
    assert {row["host_id"] for row in response_rows(response)} == {
        manage_machine.id,
        full_machine.id,
    }

def test_warranty_report_status_filter_is_applied_server_side():
    makerspace = make_space("warranty-report-filter")
    attach_asset_warranty(
        make_asset(makerspace),
        warranty_expires_on=timezone.localdate() + timedelta(days=200),
    )
    attach_printer_warranty(
        make_printer(makerspace),
        warranty_expires_on=timezone.localdate() - timedelta(days=1),
    )
    space_manager = make_member("warranty-filter-space-manager", makerspace)
    client = authenticated_client(space_manager)
    url = reverse("admin-makerspace-warranties", kwargs={"makerspace_id": makerspace.id})

    expired = client.get(f"{url}?status=expired")
    active = client.get(f"{url}?status=active")
    invalid = client.get(f"{url}?status=bogus")

    assert expired.status_code == 200
    assert [row["host_kind"] for row in response_rows(expired)] == ["machine"]
    assert active.status_code == 200
    assert [row["host_kind"] for row in response_rows(active)] == ["asset"]
    assert invalid.status_code == 400


def test_warranty_report_missing_docs_expires_before_and_count_include_uncovered():
    makerspace = make_space("warranty-report-coverage-filters")
    today = timezone.localdate()
    documented_asset = make_asset(makerspace, tag="A-DOC")
    late_asset = make_asset(makerspace, tag="A-LATE")
    uncovered_asset = make_asset(makerspace, tag="A-UNCOVERED")
    no_doc_printer = make_printer(makerspace, name="Printer No Docs")
    uncovered_printer = make_printer(makerspace, name="Printer Uncovered")
    documented_warranty = attach_asset_warranty(
        documented_asset,
        warranty_expires_on=today + timedelta(days=10),
    )
    attach_asset_warranty(late_asset, warranty_expires_on=today + timedelta(days=60))
    attach_printer_warranty(no_doc_printer, warranty_expires_on=today + timedelta(days=20))
    WarrantyDocument.objects.create(
        warranty=documented_warranty,
        object_key=f"warranty/{makerspace.id}/documented.pdf",
        original_filename="documented.pdf",
        content_type="application/pdf",
        size_bytes=123,
    )
    space_manager = make_member("warranty-coverage-filter-manager", makerspace)
    client = authenticated_client(space_manager)
    url = reverse("admin-makerspace-warranties", kwargs={"makerspace_id": makerspace.id})

    first_page = client.get(f"{url}?page_size=1")
    missing_docs = client.get(f"{url}?missing_docs=true&page_size=10")
    expires_before = client.get(f"{url}?expires_before={today + timedelta(days=30)}&page_size=10")
    missing_before = client.get(
        f"{url}?missing_docs=true&expires_before={today + timedelta(days=30)}&page_size=10"
    )

    assert first_page.status_code == 200
    assert first_page.data["count"] == 5
    assert len(response_rows(first_page)) == 1
    assert missing_docs.status_code == 200
    assert missing_docs.data["count"] == 4
    assert {row["host_id"] for row in response_rows(missing_docs) if row["host_kind"] == "asset"} == {
        late_asset.id,
        uncovered_asset.id,
    }
    assert {row["host_id"] for row in response_rows(missing_docs) if row["host_kind"] == "machine"} == {
        no_doc_printer.id,
        uncovered_printer.id,
    }
    assert expires_before.status_code == 200
    assert expires_before.data["count"] == 2
    assert [row["host_kind"] for row in response_rows(expires_before)] == ["asset", "machine"]
    assert {row["status"] for row in response_rows(expires_before)} == {"expiring_soon"}
    assert missing_before.status_code == 200
    assert missing_before.data["count"] == 1
    assert response_rows(missing_before)[0]["host_kind"] == "machine"
    assert response_rows(missing_before)[0]["host_id"] == no_doc_printer.id

def test_warranty_report_excludes_rows_for_disabled_host_modules():
    makerspace = make_space("warranty-report-modules")
    attach_asset_warranty(make_asset(makerspace))
    attach_printer_warranty(make_printer(makerspace))
    space_manager = make_member("warranty-modules-space-manager", makerspace)
    client = authenticated_client(space_manager)
    url = reverse("admin-makerspace-warranties", kwargs={"makerspace_id": makerspace.id})

    # printing disabled -> printer rows suppressed even though the action is held.
    makerspace.enabled_modules = [m for m in makerspace.enabled_modules if m != "machines"]
    makerspace.save(update_fields=["enabled_modules"])
    without_printing = client.get(url)

    # staff_admin disabled -> asset rows suppressed.
    makerspace.enabled_modules = [
        m for m in makerspace.enabled_modules if m not in {"machines", "staff_admin"}
    ] + ["machines"]
    makerspace.save(update_fields=["enabled_modules"])
    without_staff_admin = client.get(url)

    assert without_printing.status_code == 200
    assert [row["host_kind"] for row in response_rows(without_printing)] == ["asset"]
    assert without_staff_admin.status_code == 200
    assert [row["host_kind"] for row in response_rows(without_staff_admin)] == ["machine"]


def test_warranty_document_keys_are_collected_for_makerspace_purge():
    from apps.makerspaces.lifecycle import _collect_storage_keys

    makerspace = make_space("warranty-purge")
    warranty = attach_asset_warranty(make_asset(makerspace))
    document = WarrantyDocument.objects.create(
        warranty=warranty,
        object_key=f"warranty/{makerspace.id}/purge-me.pdf",
        original_filename="bill.pdf",
        content_type="application/pdf",
        size_bytes=1024,
    )

    keys = _collect_storage_keys(makerspace)

    assert document.object_key in keys


def test_cascade_delete_of_host_removes_warranty_document_object(monkeypatch):
    delete = Mock()
    monkeypatch.setattr("apps.warranty.storage.delete_object", delete)
    makerspace = make_space("warranty-cascade")
    asset = make_asset(makerspace)
    warranty = attach_asset_warranty(asset)
    object_key = f"warranty/{makerspace.id}/cascade.pdf"
    WarrantyDocument.objects.create(
        warranty=warranty,
        object_key=object_key,
        original_filename="bill.pdf",
        content_type="application/pdf",
        size_bytes=1024,
    )

    # Deleting the host asset CASCADEs to Warranty -> WarrantyDocument; the post_delete
    # signal must still clean up the private object even though no view ran.
    asset.delete()

    assert not WarrantyDocument.objects.filter(object_key=object_key).exists()
    delete.assert_called_once_with(object_key)
