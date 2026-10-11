import hashlib


import hmac


import pytest


from django.core.exceptions import ValidationError


from django.urls import reverse


from django.utils import timezone


from rest_framework.test import APIClient


from apps.inventory.models import Category, InventoryProduct, PublicAvailabilityMode


from apps.makerspaces.models import Makerspace


from tests.public_inventory_helpers import (
    api_client,
    public_makerspace,
    public_inventory_url,
    public_inventory_code_url,
    public_inventory_categories_url,
    signed_headers,
    create_product,
    public_makerspaces_url,
    get_single_product,
    PUBLIC_PRODUCT_FIELDS,
    pytestmark,
)

def test_lists_public_makerspaces(api_client, public_makerspace):
    Makerspace.objects.create(
        name="Private Lab",
        slug="private-lab",
        public_inventory_enabled=False,
    )
    Makerspace.objects.create(
        name="Fab Lab",
        slug="fab-lab",
        location="Building A",
        public_inventory_enabled=True,
    )

    response = api_client.get(public_makerspaces_url())

    assert response.status_code == 200
    assert response.data == [
        {
            "name": "Fab Lab",
            "public_code": response.data[0]["public_code"],
            "slug": "fab-lab",
            "location": "Building A",
            "map_url": "",
            "logo_url": None,
            "cover_image_url": None,
        },
        {
            "name": "Public Lab",
            "public_code": public_makerspace.public_code,
            "slug": "public-lab",
            "location": "",
            "map_url": "",
            "logo_url": None,
            "cover_image_url": None,
        },
    ]


def test_status_only_mode_hides_exact_count(api_client, public_makerspace):
    create_product(
        public_makerspace,
        public_availability_mode=PublicAvailabilityMode.STATUS_ONLY,
        total_quantity=50,
        available_quantity=50,
    )

    product = get_single_product(api_client, public_makerspace)

    assert product["availability"] == {
        "mode": "status_only",
        "label": "Available",
    }
    assert "count" not in product["availability"]


def test_exact_count_shows_count_when_enabled(api_client, public_makerspace):
    create_product(
        public_makerspace,
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
        show_public_count=True,
        total_quantity=10,
        available_quantity=8,
    )

    product = get_single_product(api_client, public_makerspace)

    assert product["availability"]["mode"] == "exact_count"
    assert product["availability"]["count"] == 8
    assert product["availability"]["label"] == "Available"


def test_exact_count_without_show_count_falls_back_to_status_only(
    api_client,
    public_makerspace,
):
    create_product(
        public_makerspace,
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
        show_public_count=False,
        total_quantity=20,
        available_quantity=2,
    )

    product = get_single_product(api_client, public_makerspace)

    assert product["availability"]["mode"] == "status_only"
    assert "count" not in product["availability"]
    assert product["availability"]["label"] == "Limited"


def test_hidden_mode_returns_null_availability(api_client, public_makerspace):
    create_product(
        public_makerspace,
        public_availability_mode=PublicAvailabilityMode.HIDDEN,
    )

    product = get_single_product(api_client, public_makerspace)

    assert product["availability"] is None


@pytest.mark.parametrize(
    ("total_quantity", "available_quantity", "expected_label"),
    [
        (4, 0, "Unavailable"),
        (15, 3, "Limited"),
        (50, 50, "Available"),
    ],
)
def test_status_labels(
    api_client,
    public_makerspace,
    total_quantity,
    available_quantity,
    expected_label,
):
    create_product(
        public_makerspace,
        public_availability_mode=PublicAvailabilityMode.STATUS_ONLY,
        total_quantity=total_quantity,
        available_quantity=available_quantity,
    )

    product = get_single_product(api_client, public_makerspace)

    assert product["availability"] == {
        "mode": "status_only",
        "label": expected_label,
    }


def test_never_exposes_internal_fields(api_client, public_makerspace):
    create_product(
        public_makerspace,
        storage_location="Locked cabinet A",
        total_quantity=10,
        available_quantity=7,
        reserved_quantity=1,
        issued_quantity=1,
        damaged_quantity=1,
        lost_quantity=0,
        show_public_count=True,
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
    )

    product = get_single_product(api_client, public_makerspace)

    internal_fields = {
        "storage_location",
        "available_quantity",
        "total_quantity",
        "reserved_quantity",
        "issued_quantity",
        "damaged_quantity",
        "lost_quantity",
        "is_public",
        "is_archived",
        "show_public_count",
        "makerspace",
        "makerspace_id",
        "public_availability_mode",
    }
    assert set(product) == PUBLIC_PRODUCT_FIELDS
    assert internal_fields.isdisjoint(product.keys())


def test_unknown_slug_returns_404(api_client):
    response = api_client.get(
        reverse("public-inventory", kwargs={"makerspace_slug": "missing-lab"}),
    )

    assert response.status_code == 404


def test_public_inventory_accepts_public_code(api_client, public_makerspace):
    create_product(public_makerspace, name="Code Product")

    response = api_client.get(public_inventory_code_url(public_makerspace))

    assert response.status_code == 200
    assert response.data["results"][0]["name"] == "Code Product"


def test_public_disabled_returns_404(api_client):
    makerspace = Makerspace.objects.create(
        name="Private Lab",
        slug="private-lab",
        public_inventory_enabled=False,
    )

    response = api_client.get(public_inventory_url(makerspace))

    assert response.status_code == 404


def test_hmac_disabled_by_default(api_client, public_makerspace):
    create_product(public_makerspace)

    response = api_client.get(public_inventory_url(public_makerspace))

    assert response.status_code == 200


def test_hmac_allows_signed_public_inventory_request(
    settings,
    api_client,
    public_makerspace,
):
    # New contract: a registered ApiClient signs with its own secret (Phase 2 Task 16).
    from apps.apiclients.models import ApiClient

    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.HMAC_MAX_CLOCK_SKEW_SECONDS = 300
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/"]
    client, secret = ApiClient.issue(label="web", allowed_origins=["http://testserver"], scopes=["public:read"])
    create_product(public_makerspace)
    path = public_inventory_url(public_makerspace)

    headers = signed_headers(path, client_id=client.client_id, secret=secret)
    headers["HTTP_ORIGIN"] = "http://testserver"
    response = api_client.get(path, **headers)

    assert response.status_code == 200


