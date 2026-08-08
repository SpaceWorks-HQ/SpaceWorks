import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.admin_api import bulk_import
from apps.admin_api.models import BulkImportJob
from apps.admin_api.serializers_bulk import BulkImportJobCreateSerializer
from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.audit.models import AuditLog
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.models import InventoryAdjustment
from tests.return_helpers import (
    authenticated_client,
    make_box,
    make_member,
    make_product,
    make_space,
    make_user,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def test_bulk_import_preview_rejects_malformed_file():
    makerspace = make_space("bulk-bad-file")
    admin = make_member("bulk-bad-file-admin", makerspace)
    bad = SimpleUploadedFile(
        "items.json", b"{ not valid json", content_type="application/json"
    )

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {"file": bad},
        format="multipart",
    )

    # Malformed user input must be a 400, not a 500.
    assert response.status_code == 400


def test_bulk_import_preview_rejects_too_many_rows():
    makerspace = make_space("bulk-too-many-rows")
    admin = make_member("bulk-too-many-rows-admin", makerspace)
    rows = [
        {"name": f"Tool {index}", "total_quantity": "1", "available_quantity": "1"}
        for index in range(bulk_import.MAX_IMPORT_ROWS + 1)
    ]

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {"rows": rows},
        format="json",
    )

    assert response.status_code == 400


def test_bulk_import_preview_rejects_oversized_upload():
    makerspace = make_space("bulk-big-file")
    admin = make_member("bulk-big-file-admin", makerspace)
    oversized = SimpleUploadedFile(
        "items.csv",
        b"x" * (bulk_import.MAX_IMPORT_UPLOAD_BYTES + 1),
        content_type="text/csv",
    )

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {"file": oversized},
        format="multipart",
    )

    assert response.status_code == 400


def test_sync_makerspace_origins_is_noop_for_global_client():
    from apps.apiclients.services import sync_makerspace_origins

    # A global client has makerspace=None; syncing must no-op, not crash.
    sync_makerspace_origins(None)


def test_inventory_patch_rejects_cross_makerspace_box():
    space_a = make_space("inv-box-a")
    space_b = make_space("inv-box-b")
    admin = make_member("inv-box-admin", space_a)
    product = make_product(space_a, name="Bench Vise")
    box_b = make_box(space_b)

    response = authenticated_client(admin).patch(
        f"/api/v1/admin/inventory/{product.id}",
        {"box": box_b.id},
        format="json",
    )

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.box_id is None


def test_inventory_patch_cannot_move_product_across_makerspaces():
    space_a = make_space("inv-mv-a")
    space_b = make_space("inv-mv-b")
    admin = make_member("inv-mv-admin", space_a)
    product = make_product(space_a, name="Soldering Station")

    response = authenticated_client(admin).patch(
        f"/api/v1/admin/inventory/{product.id}",
        {"makerspace": space_b.id, "name": "Renamed"},
        format="json",
    )

    # makerspace is read-only, so the move is silently ignored while the rest applies.
    assert response.status_code == 200
    product.refresh_from_db()
    assert product.makerspace_id == space_a.id
    assert product.name == "Renamed"


def test_superadmin_can_restrict_and_restore_user_access():
    superadmin = make_user(
        "restrictor",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    target = make_user("target", access_status=User.AccessStatus.ACTIVE)
    client = authenticated_client(superadmin)

    restricted = client.post(
        f"/api/v1/admin/users/{target.id}/restrict",
        {"reason": "Missing tool", "status": User.AccessStatus.RESTRICTED},
        format="json",
    )
    restored = client.post(f"/api/v1/admin/users/{target.id}/restore-access")

    assert restricted.status_code == 200
    assert restored.status_code == 200
    target.refresh_from_db()
    assert target.access_status == User.AccessStatus.ACTIVE
    assert target.restriction_reason == ""
    assert {"user.access_restricted", "user.access_restored"} <= set(
        AuditLog.objects.values_list("action", flat=True)
    )


def test_superadmin_cannot_restrict_or_restore_hidden_makerspace_user():
    hidden = make_space("restrict-hidden")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    target = make_member("restrict-hidden-target", hidden)
    target.access_status = User.AccessStatus.SUSPENDED
    target.restriction_reason = "Already suspended"
    target.save(update_fields=["access_status", "restriction_reason"])
    superadmin = make_user(
        "restrict-hidden-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = authenticated_client(superadmin)

    restricted = client.post(
        f"/api/v1/admin/users/{target.id}/restrict",
        {"reason": "No global access", "status": User.AccessStatus.RESTRICTED},
        format="json",
    )
    restored = client.post(f"/api/v1/admin/users/{target.id}/restore-access")

    assert restricted.status_code == 403
    assert restored.status_code == 403
    target.refresh_from_db()
    assert target.access_status == User.AccessStatus.SUSPENDED
    assert target.restriction_reason == "Already suspended"


def test_admin_bulk_import_preview_and_apply_are_makerspace_scoped():
    makerspace = make_space("bulk-import")
    admin = make_member("bulk-admin", makerspace)
    client = authenticated_client(admin)
    rows = [
        {
            "name": "Scope",
            "total_quantity": "3",
            "available_quantity": "3",
            "public_availability_mode": "status_only",
        }
    ]

    preview = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {"rows": rows},
        format="json",
    )
    applied = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply",
        {"rows": rows},
        format="json",
    )

    assert preview.status_code == 200
    assert preview.data["valid"] is True
    assert applied.status_code == 200
    assert applied.data["applied"] is True
    product = InventoryProduct.objects.get(makerspace=makerspace, name="Scope")
    assert product.total_quantity == 3
    assert product.available_quantity == 3


def test_bulk_import_apply_creates_missing_category_by_name():
    makerspace = make_space("bulk-category")
    admin = make_member("bulk-category-admin", makerspace)

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply",
        {
            "rows": [
                {
                    "Name": "Bench Supply",
                    "Total": "2",
                    "Available": "2",
                    "Category": "Electronics",
                }
            ],
            "mapping": {
                "name": "Name",
                "total_quantity": "Total",
                "available_quantity": "Available",
                "category": "Category",
            },
        },
        format="json",
    )

    assert response.status_code == 200
    category = Category.objects.get(makerspace=makerspace, name="Electronics")
    product = InventoryProduct.objects.get(makerspace=makerspace, name="Bench Supply")
    assert product.category_id == category.id
    assert AuditLog.objects.filter(action="category.created", target_id=str(category.id)).exists()


def test_bulk_import_preview_warns_on_blank_mapped_details():
    makerspace = make_space("bulk-warning")
    admin = make_member("bulk-warning-admin", makerspace)

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {
            "rows": [
                {
                    "Name": "Oscilloscope",
                    "Total": "1",
                    "Available": "1",
                    "Storage": "",
                    "Image": "",
                }
            ],
            "mapping": {
                "name": "Name",
                "total_quantity": "Total",
                "available_quantity": "Available",
                "storage_location": "Storage",
                "image_key": "Image",
            },
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["valid"] is True
    assert response.data["summary"]["warnings"] == 1
    assert response.data["warnings"][0]["row"] == 2
    assert "storage_location" in response.data["warnings"][0]["warnings"]
    assert "image_key" in response.data["warnings"][0]["warnings"]


def test_bulk_import_apply_maps_full_supported_inventory_fields():
    makerspace = make_space("bulk-full-map")
    admin = make_member("bulk-full-map-admin", makerspace)
    box = make_box(makerspace, label="BIN-A")
    image_key = f"items/{makerspace.id}/meter.png"

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply",
        {
            "rows": [
                {
                    "Item": "Clamp Meter",
                    "Total": "5",
                    "Available": "2",
                    "Reserved": "1",
                    "Issued": "1",
                    "Damaged": "1",
                    "Lost": "0",
                    "Tracking": "quantity",
                    "Public": "yes",
                    "Self checkout": "true",
                    "Show count": "1",
                    "Availability": "exact_count",
                    "Storage": "Cabinet 4",
                    "Image": image_key,
                    "Box": box.code,
                }
            ],
            "mapping": {
                "name": "Item",
                "total_quantity": "Total",
                "available_quantity": "Available",
                "reserved_quantity": "Reserved",
                "issued_quantity": "Issued",
                "damaged_quantity": "Damaged",
                "lost_quantity": "Lost",
                "tracking_mode": "Tracking",
                "is_public": "Public",
                "public_self_checkout_enabled": "Self checkout",
                "show_public_count": "Show count",
                "public_availability_mode": "Availability",
                "storage_location": "Storage",
                "image_key": "Image",
                "box_code": "Box",
            },
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["applied"] is True
    product = InventoryProduct.objects.get(makerspace=makerspace, name="Clamp Meter")
    assert product.available_quantity == 2
    assert product.reserved_quantity == 1
    assert product.issued_quantity == 1
    assert product.damaged_quantity == 1
    assert product.lost_quantity == 0
    assert product.storage_location == "Cabinet 4"
    assert product.image_key == image_key
    assert product.box_id == box.id
    assert product.public_self_checkout_enabled is True
    assert product.show_public_count is True
    assert product.public_availability_mode == "exact_count"

def test_bulk_import_job_serializer_accepts_json_mapping_string():
    serializer = BulkImportJobCreateSerializer(
        data={
            "mode": "preview",
            "rows": [{"Name": "Mapped", "Total": "1", "Available": "1"}],
            "mapping": "{\"name\":\"Name\",\"total_quantity\":\"Total\",\"available_quantity\":\"Available\"}",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["mapping"]["name"] == "Name"

def test_bulk_import_csv_upload_ignores_blank_rows():
    makerspace = make_space("bulk-blank-csv")
    admin = make_member("bulk-blank-csv-admin", makerspace)
    upload = SimpleUploadedFile(
        "items.csv",
        b"name,total_quantity,available_quantity\nCalipers,1,1\n,,\nMeter,2,2\n",
        content_type="text/csv",
    )

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {"file": upload},
        format="multipart",
    )

    assert response.status_code == 200
    assert response.data["summary"]["total"] == 2
    assert response.data["valid"] is True


def test_bulk_import_async_file_job_applies_csv_with_mapping():
    makerspace = make_space("bulk-job-file")
    admin = make_member("bulk-job-file-admin", makerspace)
    upload = SimpleUploadedFile(
        "items.csv",
        b"Item,Total,Available,Location\nSoldering Iron,3,3,Bench 1\n",
        content_type="text/csv",
    )

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/jobs",
        {
            "mode": "apply",
            "file": upload,
            "mapping": '{"name":"Item","total_quantity":"Total","available_quantity":"Available","storage_location":"Location"}',
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["status"] == BulkImportJob.Status.COMPLETED
    assert response.data["created_count"] == 1
    product = InventoryProduct.objects.get(makerspace=makerspace, name="Soldering Iron")
    assert product.total_quantity == 3
    assert product.available_quantity == 3
    assert product.storage_location == "Bench 1"

def test_bulk_import_async_apply_partially_imports_valid_rows():
    makerspace = make_space("bulk-job-partial")
    admin = make_member("bulk-job-partial-admin", makerspace)
    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/jobs",
        {
            "mode": "apply",
            "rows": [
                {"name": "Good Meter", "total_quantity": "2", "available_quantity": "2"},
                {"name": "", "total_quantity": "", "available_quantity": ""},
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == BulkImportJob.Status.COMPLETED
    assert response.data["created_count"] == 1
    assert response.data["error_count"] == 1
    assert response.data["result"]["applied"] is True
    assert response.data["result"]["partial"] is True
    assert InventoryProduct.objects.filter(makerspace=makerspace, name="Good Meter").exists()

def test_bulk_import_async_job_applies_rows_and_exposes_status():
    makerspace = make_space("bulk-job")
    admin = make_member("bulk-job-admin", makerspace)
    client = authenticated_client(admin)

    created = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/jobs",
        {
            "mode": "apply",
            "rows": [
                {
                    "name": "Async Meter",
                    "total_quantity": "2",
                    "available_quantity": "2",
                    "storage_location": "Rack 2",
                }
            ],
        },
        format="json",
    )

    assert created.status_code == 201
    assert created.data["status"] == BulkImportJob.Status.COMPLETED
    assert created.data["processed_rows"] == 1
    assert created.data["created_count"] == 1
    product = InventoryProduct.objects.get(makerspace=makerspace, name="Async Meter")
    assert product.storage_location == "Rack 2"

    status = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/jobs/{created.data['id']}"
    )

    assert status.status_code == 200
    assert status.data["status"] == BulkImportJob.Status.COMPLETED
    assert status.data["result"]["applied"] is True


def test_bulk_import_async_job_status_is_makerspace_scoped():
    owner_space = make_space("bulk-job-owner")
    other_space = make_space("bulk-job-other")
    owner = make_member("bulk-job-owner-admin", owner_space)
    other = make_member("bulk-job-other-admin", other_space)
    job = BulkImportJob.objects.create(
        makerspace=owner_space,
        actor=owner,
        mode=BulkImportJob.Mode.PREVIEW,
        rows=[{"name": "Hidden", "total_quantity": "1", "available_quantity": "1"}],
    )

    response = authenticated_client(other).get(
        f"/api/v1/admin/makerspace/{other_space.id}/inventory/import/jobs/{job.id}"
    )

    assert response.status_code == 404

def test_bulk_import_rejects_bad_quantity_buckets():
    makerspace = make_space("bulk-bad")
    admin = make_member("bulk-bad-admin", makerspace)
    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/preview",
        {
            "rows": [
                {
                    "name": "Meter",
                    "total_quantity": "1",
                    "available_quantity": "2",
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["valid"] is False
    assert response.data["errors"][0]["errors"]["total_quantity"]


def test_bulk_import_accepts_xlsx_upload():
    from io import BytesIO

    import openpyxl

    makerspace = make_space("bulk-xlsx")
    admin = make_member("bulk-xlsx-admin", makerspace)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["name", "total_quantity", "available_quantity"])
    sheet.append(["Calipers", 2, 2])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory/import/apply",
        {"file": SimpleUploadedFile("products.xlsx", stream.read())},
    )

    assert response.status_code == 200
    assert response.data["applied"] is True
    assert InventoryProduct.objects.filter(
        makerspace=makerspace,
        name="Calipers",
        total_quantity=2,
    ).exists()


def test_inventory_list_filters_before_pagination():
    makerspace = make_space("inventory-search-page")
    admin = make_member("inventory-search-page-admin", makerspace)
    for index in range(30):
        make_product(makerspace, name=f"Common Tool {index:02d}")
    target = make_product(
        makerspace,
        name="Laser Distance Meter",
        storage_location="Top Shelf",
    )

    response = authenticated_client(admin).get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory?page_size=1&q=laser"
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == target.id


def test_inventory_list_filters_low_stock_before_pagination():
    makerspace = make_space("inventory-low-stock")
    admin = make_member("inventory-low-stock-admin", makerspace)
    low = make_product(
        makerspace,
        name="Low Resin",
        total_quantity=10,
        available_quantity=2,
    )
    make_product(
        makerspace,
        name="Healthy Resin",
        total_quantity=10,
        available_quantity=8,
    )
    make_product(
        makerspace,
        name="Z Empty Resin",
        total_quantity=0,
        available_quantity=0,
    )

    response = authenticated_client(admin).get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory?page_size=1&low_stock=true"
    )

    assert response.status_code == 200
    assert response.data["count"] == 2
    assert response.data["results"][0]["id"] == low.id


def test_inventory_list_filters_archived_state():
    makerspace = make_space("inventory-archived-filter")
    admin = make_member("inventory-archived-filter-admin", makerspace)
    active = make_product(makerspace, name="Active Drill")
    archived = make_product(makerspace, name="Archived Drill", is_archived=True)
    client = authenticated_client(admin)

    active_response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory?archived=false"
    )
    archived_response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory?archived=true"
    )

    assert active_response.status_code == 200
    assert archived_response.status_code == 200
    assert [item["id"] for item in active_response.data["results"]] == [active.id]
    assert [item["id"] for item in archived_response.data["results"]] == [archived.id]


def test_inventory_create_api_writes_product_and_audit():
    makerspace = make_space("inventory-create")
    admin = make_member("inventory-create-admin", makerspace)

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory",
        {
            "name": "Logic Analyzer",
            "tracking_mode": "quantity",
            "total_quantity": 4,
            "available_quantity": 4,
            "description": "USB analyzer",
            "storage_location": "Cabinet A",
            "is_public": True,
            "public_self_checkout_enabled": False,
        },
        format="json",
    )

    assert response.status_code == 201
    product = InventoryProduct.objects.get(makerspace=makerspace, name="Logic Analyzer")
    assert product.storage_location == "Cabinet A"
    assert AuditLog.objects.filter(action="inventory.created", target_id=str(product.id)).exists()


def test_inventory_quantity_adjustment_updates_buckets_and_audit():
    makerspace = make_space("inventory-adjust")
    manager = make_member(
        "inventory-adjust-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    product = make_product(makerspace, name="Wire", available_quantity=5, damaged_quantity=1)

    response = authenticated_client(manager).post(
        f"/api/v1/admin/inventory/{product.id}/adjust-quantity",
        {
            "delta_available": -2,
            "delta_damaged": 2,
            "delta_lost": 0,
            "reason": "Found damaged during count.",
        },
        format="json",
    )

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.available_quantity == 3
    assert product.damaged_quantity == 3
    assert product.total_quantity == 6
    assert InventoryAdjustment.objects.filter(product=product, delta_available=-2).exists()
    assert AuditLog.objects.filter(action="inventory.quantity_adjusted", target_id=str(product.id)).exists()


def test_inventory_quantity_adjustment_requires_edit_inventory_in_tenant():
    makerspace = make_space("inventory-adjust-rbac")
    guest = make_handout_member("inventory-adjust-guest", makerspace)
    product = make_product(makerspace, name="Blocked Wire")

    response = authenticated_client(guest).post(
        f"/api/v1/admin/inventory/{product.id}/adjust-quantity",
        {"delta_available": 1, "reason": "No permission."},
        format="json",
    )

    assert response.status_code == 403
    product.refresh_from_db()
    assert product.available_quantity == 10


def test_inventory_quantity_adjustment_hides_cross_tenant_product_before_permission():
    own_space = make_space("inventory-adjust-own")
    other_space = make_space("inventory-adjust-other")
    guest = make_handout_member("inventory-adjust-cross-guest", own_space)
    other_product = make_product(other_space, name="Other Wire")

    response = authenticated_client(guest).post(
        f"/api/v1/admin/inventory/{other_product.id}/adjust-quantity",
        {"delta_available": 1, "reason": "No scope."},
        format="json",
    )

    assert response.status_code == 404


def test_api_client_rest_allows_makerspace_admin_and_scopes_others():
    # Feature B: API-client management is self-serve for the makerspace admin
    # (MANAGE_MAKERSPACE == Space Manager); superadmin retains access; everyone
    # else is denied / scoped out.
    makerspace = make_space("client-space")
    other_space = make_space("client-space-other")
    admin = make_member("client-admin", makerspace)  # SPACE_MANAGER
    admin_client = authenticated_client(admin)

    created = admin_client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients",
        {"label": "Public web", "allowed_origins": ["https://lab.example.com"]},
        format="json",
    )
    assert created.status_code == 201
    assert created.data["client_id"].startswith("ck_")
    assert created.data["client_secret"]  # one-time secret revealed to the makerspace admin
    assert created.data["allowed_origins"] == ["https://lab.example.com"]
    assert created.data["public_makerspace_code"] == makerspace.public_code

    listed = admin_client.get(f"/api/v1/admin/makerspace/{makerspace.id}/api-clients")
    assert listed.status_code == 200
    assert listed.data["results"][0]["client_id"] == created.data["client_id"]
    assert "client_secret" not in listed.data["results"][0]

    detail = admin_client.get(f"/api/v1/admin/api-clients/{created.data['id']}")
    assert detail.status_code == 200
    assert detail.data["client_id"] == created.data["client_id"]
    assert "client_secret" not in detail.data

    # An admin of a different makerspace cannot create here, and the client detail
    # is scoped out (404 before 403).
    other_admin = make_member("client-admin-other", other_space)
    other_client = authenticated_client(other_admin)
    denied_create = other_client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients",
        {"label": "X", "allowed_origins": ["https://x.example.com"]},
        format="json",
    )
    assert denied_create.status_code in (403, 404)
    assert other_client.get(f"/api/v1/admin/api-clients/{created.data['id']}").status_code == 404

    # A non-MANAGE_MAKERSPACE member (guest admin) is denied.
    guest = make_handout_member("client-guest", makerspace)
    denied_guest = authenticated_client(guest).get(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients"
    )
    assert denied_guest.status_code == 403

    # Superadmin still has access.
    superadmin = make_user(
        "client-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
    )
    sa_listed = authenticated_client(superadmin).get(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients"
    )
    assert sa_listed.status_code == 200

    assert ApiClient.objects.get().get_secret() == created.data["client_secret"]
    makerspace.refresh_from_db()
    assert makerspace.cors_allowed_origins == ["https://lab.example.com"]


def test_api_client_makerspace_admin_cannot_escalate_privileged_fields():
    # Review fix (P2): widening API-client management to MANAGE_MAKERSPACE must NOT let a
    # makerspace admin set the privileged knobs. Tier/scopes/client_type are forced to safe
    # defaults on create and preserved (not escalated) on update â€” superadmin-only.
    makerspace = make_space("client-escalate")
    admin = make_member("client-escalate-admin", makerspace)  # SPACE_MANAGER
    admin_client = authenticated_client(admin)

    created = admin_client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients",
        {
            "label": "Sneaky",
            "allowed_origins": ["https://lab.example.com"],
            "rate_limit_tier": "trusted",
            "scopes": ["admin:write", "inventory:write"],
            "client_type": "server",
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.data["rate_limit_tier"] == "standard"  # ignored, not "trusted"
    assert created.data["scopes"] == []  # ignored, not the admin-supplied scopes

    obj = ApiClient.objects.get(id=created.data["id"])
    assert obj.rate_limit_tier == "standard"
    assert obj.scopes == []

    # A PATCH attempting escalation is also ignored.
    patched = admin_client.patch(
        f"/api/v1/admin/api-clients/{created.data['id']}",
        {"rate_limit_tier": "trusted", "scopes": ["admin:write"]},
        format="json",
    )
    assert patched.status_code == 200
    obj.refresh_from_db()
    assert obj.rate_limit_tier == "standard"
    assert obj.scopes == []

    # A superadmin may still set the privileged knobs.
    superadmin = make_user(
        "client-escalate-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
    )
    elevated = authenticated_client(superadmin).patch(
        f"/api/v1/admin/api-clients/{created.data['id']}",
        {"rate_limit_tier": "trusted"},
        format="json",
    )
    assert elevated.status_code == 200
    obj.refresh_from_db()
    assert obj.rate_limit_tier == "trusted"


def test_hidden_makerspace_superadmin_member_cannot_escalate_api_client_fields():
    makerspace = make_space("client-hidden-escalate")
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user(
        "client-hidden-escalate-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
    )
    MakerspaceMembership.objects.create(
        user=superadmin,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = authenticated_client(superadmin)

    created = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients",
        {
            "label": "Hidden web",
            "allowed_origins": ["https://hidden.example.com"],
            "rate_limit_tier": "trusted",
            "scopes": ["admin:write"],
            "client_type": "server",
        },
        format="json",
    )
    patched = client.patch(
        f"/api/v1/admin/api-clients/{created.data['id']}",
        {"rate_limit_tier": "trusted", "scopes": ["admin:write"]},
        format="json",
    )

    assert created.status_code == 201
    assert patched.status_code == 200
    obj = ApiClient.objects.get(id=created.data["id"])
    assert obj.rate_limit_tier == "standard"
    assert obj.scopes == []


def test_member_can_request_api_key_without_secret_exposure():
    makerspace = make_space("client-request-space")
    requester = make_member("client-requester", makerspace)
    client = authenticated_client(requester)

    created = client.post(
        "/api/v1/admin/api-key-requests",
        {
            "makerspace": makerspace.id,
            "label": "Webhook server",
            "reason": "Sync inventory.",
            "allowed_origins": ["https://webhook.example.com"],
        },
        format="json",
    )
    listed = client.get(f"/api/v1/admin/api-key-requests?makerspace={makerspace.id}")

    assert created.status_code == 201
    assert created.data["status"] == ApiKeyRequest.Status.PENDING
    assert "client_secret" not in created.data
    assert "secret" not in created.data
    assert listed.status_code == 200
    assert listed.data["results"][0]["id"] == created.data["id"]
    api_key_request = ApiKeyRequest.objects.get()
    assert api_key_request.requester == requester
    assert AuditLog.objects.filter(action="api_key_request.created").exists()


def test_superadmin_cannot_request_api_key_for_hidden_makerspace_without_membership():
    hidden = make_space("client-request-hidden")
    make_member("client-request-hidden-manager", hidden)
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user(
        "client-request-hidden-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )

    response = authenticated_client(superadmin).post(
        "/api/v1/admin/api-key-requests",
        {
            "makerspace": hidden.id,
            "label": "Blocked hidden webhook",
            "allowed_origins": ["https://hidden.example.com"],
        },
        format="json",
    )

    assert response.status_code == 403
    assert ApiKeyRequest.objects.count() == 0


def test_hidden_makerspace_member_can_request_api_key():
    hidden = make_space("client-request-hidden-member")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    requester = make_member("client-request-hidden-member", hidden)

    response = authenticated_client(requester).post(
        "/api/v1/admin/api-key-requests",
        {
            "makerspace": hidden.id,
            "label": "Hidden member webhook",
            "allowed_origins": ["https://hidden-member.example.com"],
        },
        format="json",
    )

    assert response.status_code == 201
    assert ApiKeyRequest.objects.get().makerspace == hidden


def test_member_cannot_request_api_key_for_other_makerspace():
    own_space = make_space("client-request-own")
    other_space = make_space("client-request-other")
    requester = make_member("client-request-cross", own_space)

    response = authenticated_client(requester).post(
        "/api/v1/admin/api-key-requests",
        {
            "makerspace": other_space.id,
            "label": "Blocked webhook",
            "allowed_origins": ["https://blocked.example.com"],
        },
        format="json",
    )

    assert response.status_code == 403
    assert ApiKeyRequest.objects.count() == 0


def test_admin_can_manage_api_integration_settings_from_api_clients_area(monkeypatch):
    makerspace = make_space("client-settings")
    admin = make_member("client-settings-admin", makerspace)
    client = authenticated_client(admin)
    monkeypatch.setattr(
        "apps.integrations.smtp_validation.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )

    response = client.patch(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-settings",
        {
            "telegram_group_chat_id": "-100123",
            "telegram_bot_token": "bot-token",
            "smtp_host": "smtp.example.com",
            "smtp_port": 2525,
            "smtp_username": "mailer",
            "smtp_password": "smtp-secret",
            "smtp_use_tls": False,
            "smtp_from_email": "makerspace@example.com",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["public_api_key"] == makerspace.public_api_key
    assert response.data["telegram_bot_token_set"] is True
    assert response.data["smtp_password_set"] is True
    assert "telegram_bot_token" not in response.data
    assert "smtp_password" not in response.data
    makerspace.refresh_from_db()
    assert makerspace.telegram_group_chat_id == "-100123"
    assert makerspace.telegram_bot_token != "bot-token"
    assert makerspace.get_telegram_bot_token() == "bot-token"
    assert makerspace.smtp_host == "smtp.example.com"
    assert makerspace.smtp_port == 2525
    assert makerspace.smtp_username == "mailer"
    assert makerspace.smtp_password != "smtp-secret"
    assert makerspace.get_smtp_password() == "smtp-secret"
    assert makerspace.smtp_use_tls is False
    assert makerspace.smtp_from_email == "makerspace@example.com"


def test_admin_can_clear_makerspace_integration_secrets(monkeypatch):
    makerspace = make_space("client-settings-clear")
    admin = make_member("client-settings-clear-admin", makerspace)
    makerspace.set_telegram_bot_token("bot-token")
    makerspace.set_smtp_password("smtp-secret")
    makerspace.save(update_fields=["telegram_bot_token", "smtp_password", "updated_at"])
    monkeypatch.setattr(
        "apps.integrations.smtp_validation.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )

    response = authenticated_client(admin).patch(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-settings",
        {"telegram_bot_token": "", "smtp_password": ""},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["telegram_bot_token_set"] is False
    assert response.data["smtp_password_set"] is False
    makerspace.refresh_from_db()
    assert makerspace.get_telegram_bot_token() == ""
    assert makerspace.get_smtp_password() == ""


def test_makerspace_update_can_clear_integration_secrets(monkeypatch):
    makerspace = make_space("makerspace-settings-clear")
    admin = make_member("makerspace-settings-clear-admin", makerspace)
    makerspace.set_telegram_bot_token("bot-token")
    makerspace.set_smtp_password("smtp-secret")
    makerspace.save(update_fields=["telegram_bot_token", "smtp_password", "updated_at"])
    monkeypatch.setattr(
        "apps.integrations.smtp_validation.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )

    response = authenticated_client(admin).patch(
        f"/api/v1/admin/makerspaces/{makerspace.id}",
        {"telegram_bot_token": "", "smtp_password": ""},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["telegram_bot_token_set"] is False
    assert response.data["smtp_password_set"] is False
    makerspace.refresh_from_db()
    assert makerspace.get_telegram_bot_token() == ""
    assert makerspace.get_smtp_password() == ""


def test_space_manager_can_change_features_but_not_modules():
    makerspace = make_space("makerspace-feature-settings")
    makerspace.enabled_modules = ["public_inventory"]
    makerspace.enabled_features = []
    makerspace.save(update_fields=["enabled_modules", "enabled_features"])
    manager = make_member("makerspace-feature-settings-manager", makerspace)
    client = authenticated_client(manager)
    url = f"/api/v1/admin/makerspaces/{makerspace.id}"

    enabled = client.patch(
        url,
        {"enabled_features": ["inventory.self_checkout"]},
        format="json",
    )

    assert enabled.status_code == 200
    assert enabled.data["enabled_features"] == ["inventory.self_checkout"]
    makerspace.refresh_from_db()
    assert makerspace.enabled_features == ["inventory.self_checkout"]
    feature_audit = AuditLog.objects.get(
        action="makerspace.features_changed", makerspace=makerspace
    )
    assert feature_audit.meta == {
        "before": [],
        "after": ["inventory.self_checkout"],
    }

    modules = client.patch(url, {"enabled_modules": ["machines"]}, format="json")

    assert modules.status_code == 403
    makerspace.refresh_from_db()
    assert makerspace.enabled_modules == ["public_inventory"]
    assert AuditLog.objects.filter(
        action="makerspace.features_changed", makerspace=makerspace
    ).count() == 1

def test_api_client_secret_rotation_returns_new_secret_once():
    makerspace = make_space("client-rotate")
    admin = make_member("client-rotate-admin", makerspace)
    api_client, old_secret = ApiClient.issue(
        label="Webhook",
        makerspace=makerspace,
        allowed_origins=["https://lab.example.com"],
        created_by=admin,
    )
    client = authenticated_client(admin)

    response = client.post(
        f"/api/v1/admin/api-clients/{api_client.id}/rotate-secret",
        format="json",
    )

    assert response.status_code == 200
    assert response.data["id"] == api_client.id
    assert response.data["client_secret"]
    assert response.data["client_secret"] != old_secret
    api_client.refresh_from_db()
    assert api_client.get_secret() == response.data["client_secret"]
    assert AuditLog.objects.filter(
        action="api_client.secret_rotated",
        target_id=str(api_client.id),
    ).exists()

    listed = client.get(f"/api/v1/admin/makerspace/{makerspace.id}/api-clients")
    detail = client.get(f"/api/v1/admin/api-clients/{api_client.id}")
    assert "client_secret" not in listed.data["results"][0]
    assert "client_secret" not in detail.data

def test_admin_cannot_manage_other_makerspace_api_clients():
    own_space = make_space("own-api")
    other_space = make_space("other-api")
    admin = make_member("own-api-admin", own_space)

    response = authenticated_client(admin).post(
        f"/api/v1/admin/makerspace/{other_space.id}/api-clients",
        {
            "label": "Blocked",
            "allowed_origins": ["https://blocked.example.com"],
        },
        format="json",
    )

    assert response.status_code == 403
    assert ApiClient.objects.count() == 0


def test_superadmin_can_create_and_list_inventory_manager():
    makerspace = make_space("inventory-manager-superadmin")
    superadmin = make_user(
        "inventory-manager-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = authenticated_client(superadmin)

    created = client.post(
        "/api/v1/admin/users/inventory-managers",
        {
            "username": "new-inventory-manager",
            "email": "new-inventory-manager@example.com",
            "makerspace_id": makerspace.id,
            "role": "inventory_manager",
        },
        format="json",
    )
    listed = client.get("/api/v1/admin/users/inventory-managers")

    assert created.status_code == 201
    assert created.data["makerspace_id"] == makerspace.id
    assert created.data["role"] == "inventory_manager"
    assert created.data["user"]["role"] == User.Role.REQUESTER
    assert listed.status_code == 200
    assert [item["id"] for item in listed.data["results"]] == [created.data["id"]]


def test_create_staff_rejects_nonexistent_makerspace_without_orphaning_user():
    superadmin = make_user(
        "staff-create-bad-space",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = authenticated_client(superadmin)

    response = client.post(
        "/api/v1/admin/users/inventory-managers",
        {
            "username": "orphan-candidate",
            "email": "orphan-candidate@example.com",
            "makerspace_id": 999999,
            "role": "inventory_manager",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "makerspace_id" in response.data
    assert not User.objects.filter(username="orphan-candidate").exists()


def test_space_manager_can_create_inventory_manager_in_own_makerspace():
    makerspace = make_space("inventory-manager-delegated")
    space_manager = make_member("inventory-manager-delegator", makerspace)

    response = authenticated_client(space_manager).post(
        "/api/v1/admin/users/inventory-managers",
        {
            "username": "delegated-inventory-manager",
            "email": "delegated-inventory-manager@example.com",
            "makerspace_id": makerspace.id,
            "role": "inventory_manager",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["makerspace_id"] == makerspace.id
    assert response.data["role"] == MakerspaceMembership.Role.INVENTORY_MANAGER
    assert response.data["user"]["role"] == User.Role.REQUESTER


def test_space_manager_cannot_create_or_list_cross_tenant_inventory_managers():
    own_space = make_space("inventory-manager-own")
    other_space = make_space("inventory-manager-other")
    space_manager = make_member("inventory-manager-own-admin", own_space)
    own_inventory_manager = make_member(
        "inventory-manager-own-user",
        own_space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    other_inventory_manager = make_member(
        "inventory-manager-other-user",
        other_space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    client = authenticated_client(space_manager)

    created = client.post(
        "/api/v1/admin/users/inventory-managers",
        {
            "username": "blocked-inventory-manager",
            "email": "blocked-inventory-manager@example.com",
            "makerspace_id": other_space.id,
            "role": "inventory_manager",
        },
        format="json",
    )
    listed = client.get("/api/v1/admin/users/inventory-managers")

    assert created.status_code == 403
    assert listed.status_code == 200
    listed_usernames = [item["user"]["username"] for item in listed.data["results"]]
    assert own_inventory_manager.username in listed_usernames
    assert other_inventory_manager.username not in listed_usernames
