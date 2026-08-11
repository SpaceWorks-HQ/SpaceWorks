from datetime import timedelta
from decimal import Decimal
import json
import re
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box, QrCode
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.inventory.models import InventoryAsset, InventoryProduct, PublicAvailabilityMode
from apps.inventory.public_stats import build_public_stats
from apps.inventory.public_stats_hardware import public_display_name
from apps.inventory.views_public_stats import PublicMakerspaceStatsView
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db

DATE_VALUE_KEYS = {"period", "due", "since", "created_at"}
PHONE_SHAPED_RE = re.compile(r"\d{7,}")
FORBIDDEN_RESPONSE_KEYS = {
    "email",
    "phone",
    "contact_email",
    "contact_phone",
    "printer_id",
    "spool_id",
    "product_id",
    "request_id",
    "makerspace_id",
    "reference_id",
    "asset_tag",
    "serial_number",
    "units",
    "target_label",
    "remaining_grams",
    "price",
    "payment_status",
    "paid_at",
    "damaged_quantity",
    "missing_quantity",
    "assets",
    "location",
    "storage_location",
    "box",
    "qr",
    "scan",
    "evidence",
}
FORBIDDEN_RESPONSE_KEY_PREFIXES = (
    "payment",
    "damaged",
    "missing",
    "box",
    "qr",
    "scan",
    "evidence",
)


def make_space(slug="public-stats", *, printing=False):
    modules = ["public_inventory"]
    if printing:
        modules.append("printing")
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        public_inventory_enabled=True,
        public_stats_enabled=True,
        public_stats_show_holder_names=True,
        enabled_modules=modules,
    )


def make_user(username, **overrides):
    defaults = {
        "email": f"{username}@example.com" if "@" not in username else "",
        "access_status": User.AccessStatus.ACTIVE,
    }
    defaults.update(overrides)
    return User.objects.create_user(username=username, **defaults)


def make_product(makerspace, name, **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": name,
        "is_public": True,
        "is_archived": False,
        "total_quantity": 5,
        "available_quantity": 5,
        "show_public_count": True,
        "public_availability_mode": PublicAvailabilityMode.EXACT_COUNT,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def public_stats_url(makerspace_or_slug):
    slug = getattr(makerspace_or_slug, "slug", makerspace_or_slug)
    return reverse("v1:public-makerspace-stats", kwargs={"makerspace_slug": slug})


def make_request_item(
    makerspace,
    product,
    username,
    *,
    display_name=None,
    requester_name="",
    quantity=1,
    returned=0,
    status=HardwareRequest.Status.ISSUED,
    requester=None,
):
    requester = requester or make_user(username)
    issued_at = timezone.now() - timedelta(days=1)
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=display_name or requester.username,
        requester_name=requester_name,
        status=status,
        issued_at=issued_at,
        return_due_at=issued_at + timedelta(days=7),
    )
    item = HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=quantity,
        accepted_quantity=quantity,
        issued_quantity=quantity,
        returned_quantity=returned,
    )
    return request, item


def make_public_tool_loan(makerspace, request, requester, *, source):
    due_at = timezone.now() + timedelta(days=3)
    loan = PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=request,
        requester=requester,
        target_type="product",
        target_id=request.items.first().product_id,
        target_label="hidden target label",
        status=PublicToolLoan.Status.CHECKED_OUT,
        source=source,
        due_at=due_at,
    )
    loan.checked_out_at = timezone.now() - timedelta(hours=4)
    loan.save(update_fields=["checked_out_at"])
    return loan


def assert_public_stats_schema(payload):
    assert set(payload) == {'machines', 'printing', 'hardware', 'current_loans'}
    if payload['machines'] is not None:
        assert set(payload['machines']) == {'usage_hours'}
    if payload["printing"] is not None:
        assert set(payload["printing"]) == {
            "hours_all_time",
            "hours_this_month",
            "busiest_printer",
            "per_printer",
            "grams_all_time",
            "by_brand",
            "jobs",
            "filament_trend",
        }
        if payload["printing"]["busiest_printer"] is not None:
            assert set(payload["printing"]["busiest_printer"]) == {
                "name",
                "model",
                "hours",
                "completed",
                "image_url",
            }
        assert all(
            set(row) == {"name", "model", "jobs", "hours", "grams", "image_url"}
            for row in payload["printing"]["per_printer"]
        )
        assert all(set(row) == {"brand", "grams"} for row in payload["printing"]["by_brand"])
        assert set(payload["printing"]["jobs"]) == {"completed", "status_counts", "queue"}
        assert set(payload["printing"]["jobs"]["status_counts"]) == {
            "pending",
            "accepted",
            "printing",
            "completed",
            "collected",
            "failed",
            "rejected",
        }
        assert set(payload["printing"]["jobs"]["queue"]) == {
            "pending",
            "accepted",
            "printing",
        }
        assert all(
            set(row) == {"period", "grams"}
            for row in payload["printing"]["filament_trend"]
        )
    assert set(payload["hardware"]) == {
        "most_popular",
        "tools_out",
        "library",
        "recently_added",
    }
    assert all(
        set(row) == {"name", "times_lent", "total_quantity_lent"}
        for row in payload["hardware"]["most_popular"]
    )
    assert all(
        set(row) == {"name", "quantity_out"}
        for row in payload["hardware"]["tools_out"]
    )
    assert set(payload["hardware"]["library"]) == {
        "currently_out_count",
        "library_size",
        "available_count",
    }
    assert all(
        set(row) == {"name", "created_at"}
        for row in payload["hardware"]["recently_added"]
    )
    assert all(set(row) == {"item_name", "holder_name", "due", "since"} for row in payload["current_loans"])


def assert_no_public_stats_value_leaks(value, parent_key=""):
    if isinstance(value, dict):
        for key, child in value.items():
            assert_no_public_stats_value_leaks(child, key)
        return
    if isinstance(value, list):
        for child in value:
            assert_no_public_stats_value_leaks(child, parent_key)
        return
    if not isinstance(value, str):
        return

    assert "@" not in value
    assert "checkin_" not in value.lower()
    if parent_key not in DATE_VALUE_KEYS:
        assert not PHONE_SHAPED_RE.search(value)


def assert_no_forbidden_public_stats_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            assert normalized not in FORBIDDEN_RESPONSE_KEYS
            assert not normalized.endswith("_id")
            assert not normalized.startswith(FORBIDDEN_RESPONSE_KEY_PREFIXES)
            assert_no_forbidden_public_stats_keys(child)
        return
    if isinstance(value, list):
        for child in value:
            assert_no_forbidden_public_stats_keys(child)


def test_public_display_name_prefers_safe_requester_name_and_masks_unsafe_names():
    requester = make_user(
        "plainuser",
        first_name="Real",
        last_name="Name",
    )

    assert public_display_name(
        request=SimpleNamespace(
            requester_name="Display Name",
            requester_username="Ignored Username",
        ),
        requester=requester,
    ) == "Display Name"
    assert public_display_name(
        request=SimpleNamespace(
            requester_name="person@example.com",
            requester_username="person@example.com",
        ),
    ) == "Member"
    assert public_display_name(
        request=SimpleNamespace(
            requester_name="member 9876543210",
            requester_username="member 9876543210",
        ),
    ) == "Member"
    # Phone digits separated by common separators must still be masked.
    assert public_display_name(
        request=SimpleNamespace(
            requester_name="555-123-4567",
            requester_username="555-123-4567",
        ),
    ) == "Member"
    assert public_display_name(
        request=SimpleNamespace(
            requester_name="(555) 123 4567",
            requester_username="(555) 123 4567",
        ),
    ) == "Member"
    assert public_display_name(
        request=SimpleNamespace(
            requester_name="checkin_" + "a" * 64,
            requester_username="checkin_" + "a" * 64,
        ),
    ) == "Member"
    long_name = "Very Long Member Name " * 5
    assert public_display_name(
        request=SimpleNamespace(
            requester_name=long_name,
            requester_username="ignored",
        ),
    ) == long_name[:60]
    assert public_display_name(
        request=SimpleNamespace(requester_name="", requester_username="Fallback Name"),
    ) == "Fallback Name"
    assert public_display_name(requester=make_user("accepted_name")) == "accepted_name"


def test_current_loans_show_safe_requester_name_and_mask_unsafe_names():
    makerspace = make_space("stats-requester-names")
    cases = [
        ("Clean Tool", "Clean Maker", "holder-clean", "Clean Maker"),
        ("Email Tool", "borrower@example.com", "leaky@example.com", "Member"),
        ("Phone Tool", "555-123-4567", "555-123-4567", "Member"),
        ("Hash Tool", "checkin_" + "a" * 64, "checkin_" + "b" * 64, "Member"),
    ]
    for product_name, requester_name, username, expected in cases:
        product = make_product(
            makerspace,
            product_name,
            available_quantity=4,
            issued_quantity=1,
        )
        request, _ = make_request_item(
            makerspace,
            product,
            username,
            requester_name=requester_name,
            display_name=username,
        )
        request.requester_contact_email = f"{product_name.lower().replace(' ', '-')}@example.com"
        request.requester_contact_phone = "+15550109999"
        request.save(
            update_fields=[
                "requester_contact_email",
                "requester_contact_phone",
                "updated_at",
            ]
        )

    rows = build_public_stats(makerspace)["current_loans"]

    holders_by_item = {row["item_name"]: row["holder_name"] for row in rows}
    assert holders_by_item == {item: expected for item, _name, _username, expected in cases}
    body = json.dumps(rows, default=str)
    assert "example.com" not in body
    assert "+15550109999" not in body


def test_current_loans_excludes_hidden_availability_products():
    makerspace = make_space("stats-hidden-loans")
    shown = make_product(
        makerspace,
        "Shown Tool",
        available_quantity=2,
        issued_quantity=1,
    )
    hidden = make_product(
        makerspace,
        "Hidden Tool",
        available_quantity=2,
        issued_quantity=1,
        public_availability_mode=PublicAvailabilityMode.HIDDEN,
    )
    make_request_item(makerspace, shown, "shown-holder")
    make_request_item(makerspace, hidden, "hidden-holder")

    loans = build_public_stats(makerspace)["current_loans"]

    names = [row["item_name"] for row in loans]
    assert "Shown Tool" in names
    assert "Hidden Tool" not in names


def test_non_public_products_are_excluded_from_hardware_stats_and_current_loans():
    makerspace = make_space("stats-public-only")
    public_product = make_product(
        makerspace,
        "Public Drill",
        total_quantity=5,
        available_quantity=3,
        issued_quantity=2,
    )
    private_product = make_product(
        makerspace,
        "Private Scope",
        is_public=False,
        total_quantity=50,
        available_quantity=20,
        issued_quantity=30,
    )
    make_request_item(makerspace, public_product, "public-holder", quantity=2)
    make_request_item(makerspace, private_product, "private-holder", quantity=10)

    stats = build_public_stats(makerspace)

    assert stats["printing"] is None
    assert stats["hardware"]["most_popular"] == [
        {"name": "Public Drill", "times_lent": 1, "total_quantity_lent": 2}
    ]
    assert stats["hardware"]["tools_out"] == [
        {"name": "Public Drill", "quantity_out": 2}
    ]
    assert stats["hardware"]["library"] == {
        "currently_out_count": 2,
        "library_size": 1,
        "available_count": 3,
    }
    assert [row["name"] for row in stats["hardware"]["recently_added"]] == [
        "Public Drill"
    ]
    assert [row["item_name"] for row in stats["current_loans"]] == ["Public Drill"]


def test_public_stats_exact_count_tiles_exclude_hidden_and_status_only_products():
    makerspace = make_space("stats-count-visibility")
    make_product(
        makerspace,
        "Exact Counter",
        available_quantity=2,
        issued_quantity=1,
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
        show_public_count=True,
    )
    make_product(
        makerspace,
        "Status Only",
        total_quantity=10,
        available_quantity=6,
        issued_quantity=4,
        public_availability_mode=PublicAvailabilityMode.STATUS_ONLY,
        show_public_count=True,
    )
    make_product(
        makerspace,
        "Hidden Count",
        total_quantity=10,
        available_quantity=8,
        issued_quantity=2,
        public_availability_mode=PublicAvailabilityMode.HIDDEN,
        show_public_count=True,
    )
    make_product(
        makerspace,
        "Exact Mode Without Count",
        total_quantity=12,
        available_quantity=9,
        issued_quantity=3,
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
        show_public_count=False,
    )

    stats = build_public_stats(makerspace)

    assert stats["hardware"]["tools_out"] == [
        {"name": "Exact Counter", "quantity_out": 1}
    ]
    assert stats["hardware"]["library"] == {
        "currently_out_count": 1,
        "library_size": 4,
        "available_count": 2,
    }


def test_self_checkout_and_direct_handout_borrowers_appear_in_current_loans():
    makerspace = make_space("stats-current-loans")
    self_product = make_product(
        makerspace,
        "Logic Analyzer",
        available_quantity=4,
        issued_quantity=1,
    )
    direct_product = make_product(
        makerspace,
        "Thermal Camera",
        available_quantity=4,
        issued_quantity=1,
    )
    self_user = make_user("selfcheckout")
    direct_user = make_user("directborrower")
    self_request, _ = make_request_item(
        makerspace,
        self_product,
        "selfcheckout",
        display_name="Self Checkout",
        requester=self_user,
    )
    direct_request, _ = make_request_item(
        makerspace,
        direct_product,
        "directborrower",
        display_name="Direct Borrower",
        requester=direct_user,
    )
    make_public_tool_loan(
        makerspace,
        self_request,
        self_user,
        source=PublicToolLoan.Source.PUBLIC_SELF_CHECKOUT,
    )
    make_public_tool_loan(
        makerspace,
        direct_request,
        direct_user,
        source=PublicToolLoan.Source.ADMIN_DIRECT,
    )

    rows = build_public_stats(makerspace)["current_loans"]

    holders_by_item = {row["item_name"]: row["holder_name"] for row in rows}
    assert holders_by_item == {
        "Logic Analyzer": "Self Checkout",
        "Thermal Camera": "Direct Borrower",
    }
    assert all(set(row) == {"item_name", "holder_name", "due", "since"} for row in rows)


def test_public_stats_endpoint_returns_404_when_stats_toggle_is_disabled():
    client = APIClient()
    makerspace = make_space("stats-toggle-off")
    makerspace.public_stats_enabled = False
    makerspace.save(update_fields=["public_stats_enabled"])

    response = client.get(public_stats_url(makerspace))

    assert response.status_code == 404


def test_public_stats_returns_404_for_archived_unknown_and_disabled_makerspaces():
    client = APIClient()
    archived = make_space("stats-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    disabled = make_space("stats-disabled")
    disabled.public_inventory_enabled = False
    disabled.save(update_fields=["public_inventory_enabled"])
    module_off = make_space("stats-module-off")
    module_off.enabled_modules = []
    module_off.save(update_fields=["enabled_modules"])
    stats_off = make_space("stats-feature-off")
    stats_off.public_stats_enabled = False
    stats_off.save(update_fields=["public_stats_enabled"])

    assert client.get(public_stats_url(archived)).status_code == 404
    assert client.get(public_stats_url("missing-stats-space")).status_code == 404
    assert client.get(public_stats_url(disabled)).status_code == 404
    assert client.get(public_stats_url(module_off)).status_code == 404
    assert client.get(public_stats_url(stats_off)).status_code == 404


def test_public_stats_toggle_round_trips_through_admin_serializer_and_bootstrap():
    makerspace = make_space("stats-toggle-roundtrip")
    makerspace.public_stats_enabled = False
    makerspace.save(update_fields=["public_stats_enabled"])
    manager = make_user(
        "stats-toggle-manager",
        role=User.Role.SPACE_MANAGER,
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=manager,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(manager)

    response = client.patch(
        f"/api/v1/admin/makerspaces/{makerspace.id}",
        {"public_stats_enabled": True},
        format="json",
    )
    bootstrap_response = APIClient().get(f"/api/v1/bootstrap?slug={makerspace.slug}")

    assert response.status_code == 200
    assert response.data["public_stats_enabled"] is True
    makerspace.refresh_from_db()
    assert makerspace.public_stats_enabled is True
    assert bootstrap_response.status_code == 200
    assert bootstrap_response.data["makerspace"]["public_stats_enabled"] is True


def test_public_stats_response_has_no_leaky_values_or_forbidden_keys():
    client = APIClient()
    makerspace = make_space("stats-no-leaks", printing=True)
    product = make_product(
        makerspace,
        "Thermal Camera",
        total_quantity=3,
        available_quantity=2,
        issued_quantity=1,
    )
    unsafe_user = make_user("checkin_" + "a" * 16, email="unsafe@example.com")
    make_request_item(
        makerspace,
        product,
        "checkin-user",
        display_name="leaky@example.com",
        requester=unsafe_user,
    )

    response = client.get(public_stats_url(makerspace))

    assert response.status_code == 200
    assert_no_public_stats_value_leaks(response.data)
    assert_no_forbidden_public_stats_keys(response.data)


def test_public_stats_seeded_sentinels_never_appear_in_response_body():
    client = APIClient()
    makerspace = make_space("stats-sentinels", printing=True)
    sentinels = [
        "SENTINELEMAIL@x.com",
        "SENTINELPHONE5551234",
        "SENTINELSTORAGE",
        "SENTINELASSETTAG",
        "SENTINELSERIAL",
        "SENTINELBOX",
        "SENTINELQR",
    ]
    box = Box.objects.create(
        makerspace=makerspace,
        label="SENTINELBOX",
        location="SENTINELSTORAGE",
    )
    product = make_product(
        makerspace,
        "Safe Public Tool",
        box=box,
        storage_location="SENTINELSTORAGE",
        total_quantity=4,
        available_quantity=3,
        issued_quantity=1,
    )
    InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        box=box,
        asset_tag="SENTINELASSETTAG",
        serial_number="SENTINELSERIAL",
    )
    QrCode.objects.create(
        makerspace=makerspace,
        payload="SENTINELQR",
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
    )
    requester = make_user(
        "SENTINELEMAIL@x.com",
        email="SENTINELEMAIL@x.com",
        first_name="",
        last_name="",
    )
    make_request_item(
        makerspace,
        product,
        "SENTINELEMAIL@x.com",
        display_name="SENTINELPHONE5551234",
        requester=requester,
    )

    response = client.get(public_stats_url(makerspace))

    assert response.status_code == 200
    body = response.content.decode()
    for sentinel in sentinels:
        assert sentinel not in body
    assert_no_public_stats_value_leaks(json.loads(body))
    assert_no_forbidden_public_stats_keys(response.data)


def test_public_stats_view_uses_public_stats_throttle_scope():
    assert PublicMakerspaceStatsView.throttle_scope == "public_stats"


def test_openapi_schema_includes_public_stats_path():
    client = APIClient()
    response = client.get(reverse("schema"))

    assert response.status_code == 200
    schema_text = response.content.decode()
    assert "/api/v1/public/{makerspace_slug}/stats/" in schema_text
