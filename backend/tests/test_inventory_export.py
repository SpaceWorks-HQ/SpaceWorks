import csv
from io import StringIO

import pytest

from apps.accounts.models import User
from apps.boxes.models import Box
from apps.inventory.models import Category
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_product, make_space
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


HEADER = [
    "name",
    "category",
    "tracking_mode",
    "total_quantity",
    "available_quantity",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
    "needs_fix_quantity",
    "is_public",
    "public_availability_mode",
    "show_public_count",
    "public_self_checkout_enabled",
    "storage_location",
    "box_code",
    "is_archived",
    "created_at",
]


def export_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/inventory/export"


def read_csv_rows(response):
    return list(csv.reader(StringIO(response.content.decode())))


def make_category(makerspace, name="Tools", slug="tools"):
    return Category.objects.create(makerspace=makerspace, name=name, slug=slug)


def make_box(makerspace, label="Shelf A"):
    return Box.objects.create(makerspace=makerspace, label=label)


def test_csv_export_all_items_includes_rows_and_total_summary():
    makerspace = make_space("inventory-export-csv")
    admin = make_member("inventory-export-csv-admin", makerspace)
    category = make_category(makerspace)
    box = make_box(makerspace)
    make_product(
        makerspace,
        name="Alpha Drill",
        category=category,
        box=box,
        total_quantity=5,
        available_quantity=3,
        reserved_quantity=1,
        issued_quantity=1,
        storage_location="Cabinet 1",
    )
    make_product(
        makerspace,
        name="Beta Saw",
        total_quantity=7,
        available_quantity=4,
        damaged_quantity=1,
    )

    response = authenticated_client(admin).get(export_url(makerspace))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    rows = read_csv_rows(response)
    assert rows[0] == HEADER
    assert rows[1][0] == "Alpha Drill"
    assert rows[1][1] == "Tools"
    assert rows[1][3] == "5"
    assert rows[1][4] == "3"
    assert rows[1][14] == "Cabinet 1"
    assert rows[1][15] == box.code
    assert rows[2][0] == "Beta Saw"
    assert rows[3][0] == "TOTAL (2 items)"
    assert rows[3][3] == "12"
    assert rows[3][4] == "7"


def test_xlsx_export_returns_spreadsheet_content_type():
    makerspace = make_space("inventory-export-xlsx")
    admin = make_member("inventory-export-xlsx-admin", makerspace)
    make_product(makerspace, name="Calipers")

    response = authenticated_client(admin).get(f"{export_url(makerspace)}?format=xlsx")

    assert response.status_code == 200
    assert response["Content-Type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content.startswith(b"PK")


def test_export_ids_selects_only_requested_products_in_makerspace():
    makerspace = make_space("inventory-export-ids")
    other_space = make_space("inventory-export-ids-other")
    admin = make_member("inventory-export-ids-admin", makerspace)
    selected = make_product(makerspace, name="Selected Meter", total_quantity=4, available_quantity=2)
    make_product(makerspace, name="Ignored Meter", total_quantity=9, available_quantity=9)
    other = make_product(other_space, name="Other Space Meter", total_quantity=11, available_quantity=11)

    response = authenticated_client(admin).get(
        f"{export_url(makerspace)}?ids={selected.id},not-an-id,{other.id}"
    )

    assert response.status_code == 200
    rows = read_csv_rows(response)
    assert [row[0] for row in rows] == ["name", "Selected Meter", "TOTAL (1 items)"]
    assert rows[2][3] == "4"
    assert rows[2][4] == "2"


def test_export_invalid_format_returns_validation_error():
    makerspace = make_space("inventory-export-bad-format")
    admin = make_member("inventory-export-bad-format-admin", makerspace)

    response = authenticated_client(admin).get(f"{export_url(makerspace)}?format=pdf")

    assert response.status_code == 400
    assert response.data == {"format": "Use csv or xlsx."}


def test_cross_makerspace_viewer_cannot_export_and_missing_space_is_404():
    own_space = make_space("inventory-export-own")
    other_space = make_space("inventory-export-other")
    viewer = make_member(
        "inventory-export-outsider",
        own_space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    make_product(other_space, name="Hidden Drill")
    client = authenticated_client(viewer)

    forbidden = client.get(export_url(other_space))
    missing = client.get("/api/v1/admin/makerspace/999999/inventory/export")

    assert forbidden.status_code == 403
    assert missing.status_code == 404


def test_guest_admin_with_only_view_inventory_cannot_export():
    # The bulk export carries storage_location/box_code, so it is gated on
    # EDIT_INVENTORY. A handout-only guest admin (VIEW_INVENTORY but not
    # EDIT_INVENTORY) must be forbidden even within its own makerspace.
    makerspace = make_space("inventory-export-guest")
    guest = make_handout_member("inventory-export-guest-admin", makerspace)
    make_product(makerspace, name="Sensitive Drill")

    response = authenticated_client(guest).get(export_url(makerspace))

    assert response.status_code == 403
