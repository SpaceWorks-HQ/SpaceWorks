import pytest

from apps.accounts.models import User
from tests.return_helpers import (
    authenticated_client,
    make_issued_request,
    make_member,
    make_product,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db


def test_report_json_adds_typed_rows_without_changing_raw_rows_or_csv_export():
    makerspace = make_space("reports-typed")
    manager = make_member("reports-typed-manager", makerspace)
    product = make_product(makerspace, name="Typed Scope")
    make_issued_request(makerspace, manager, [(product, 2)])
    client = authenticated_client(manager)

    response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/analytics/most-lent"
    )

    assert response.status_code == 200
    assert response.data["rows"] == [
        ["product_name", "times_lent", "total_quantity_lent"],
        ["Typed Scope", 1, 2],
    ]
    assert response.data["typed_rows"] == [
        {
            "product_name": "Typed Scope",
            "times_lent": 1,
            "total_quantity_lent": 2,
        }
    ]

    export = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/reports/most-lent/export"
    )

    assert export.status_code == 200
    lines = export.content.decode().splitlines()
    # Line 0 is the per-file provenance row (who/when/which report); the data follows.
    assert lines[0].startswith("# generated_at=")
    assert lines[1:] == [
        "product_name,times_lent,total_quantity_lent",
        "Typed Scope,1,2",
    ]


def test_aggregate_report_typed_rows_include_makerspace_scope():
    space_a = make_space("reports-typed-a")
    space_b = make_space("reports-typed-b")
    manager_a = make_member("reports-typed-manager-a", space_a)
    manager_b = make_member("reports-typed-manager-b", space_b)
    product_a = make_product(space_a, name="Typed Drill")
    product_b = make_product(space_b, name="Typed Meter")
    make_issued_request(space_a, manager_a, [(product_a, 2)])
    make_issued_request(space_b, manager_b, [(product_b, 3)])
    superadmin = make_user(
        "reports-typed-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )

    response = authenticated_client(superadmin).get(
        "/api/v1/admin/analytics/taken-items"
    )

    assert response.status_code == 200
    assert response.data["rows"][0] == [
        "makerspace_id",
        "product",
        "issued_quantity",
    ]
    assert sorted(response.data["typed_rows"], key=lambda row: row["product"]) == [
        {
            "makerspace_id": space_a.id,
            "product": "Typed Drill",
            "issued_quantity": 2,
        },
        {
            "makerspace_id": space_b.id,
            "product": "Typed Meter",
            "issued_quantity": 3,
        },
    ]