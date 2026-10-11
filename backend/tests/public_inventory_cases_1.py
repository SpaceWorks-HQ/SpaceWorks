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

def test_public_lookup_prefers_slug_over_colliding_public_code():
    # A user-controlled slug can collide with another makerspace's 4-char public_code.
    # The lookup must resolve deterministically (slug wins) instead of raising
    # MultipleObjectsReturned -> 500.
    from apps.makerspaces.lookup import get_public_makerspace

    by_slug = Makerspace.objects.create(name="Slug Space", slug="ABCD")
    by_code = Makerspace.objects.create(name="Code Space", slug="code-space")
    by_code.public_code = "ABCD"
    by_code.save(update_fields=["public_code"])

    assert get_public_makerspace("ABCD").pk == by_slug.pk


def test_lists_only_public_non_archived_products(api_client, public_makerspace):
    create_product(public_makerspace, name="Public Product")
    create_product(public_makerspace, name="Private Product", is_public=False)
    create_product(public_makerspace, name="Archived Product", is_archived=True)

    response = api_client.get(public_inventory_url(public_makerspace))

    assert response.status_code == 200
    names = [product["name"] for product in response.data["results"]]
    assert names == ["Public Product"]
    assert "Private Product" not in names
    assert "Archived Product" not in names


def test_public_inventory_searches_name_and_description(api_client, public_makerspace):
    create_product(public_makerspace, name="Oscilloscope")
    create_product(
        public_makerspace,
        name="Bench Supply",
        description="Regulated soldering station power supply",
    )
    create_product(public_makerspace, name="Calipers")

    response = api_client.get(public_inventory_url(public_makerspace), {"q": "solder"})

    assert response.status_code == 200
    assert [product["name"] for product in response.data["results"]] == [
        "Bench Supply"
    ]


def test_public_product_payload_includes_category_fields(api_client, public_makerspace):
    category = Category.objects.create(
        makerspace=public_makerspace,
        name="Sensors",
        slug="sensors-extra",
    )
    create_product(public_makerspace, name="Distance Sensor", category=category)

    product = get_single_product(api_client, public_makerspace)

    assert product["category_id"] == category.id
    assert product["category_name"] == "Sensors"
    assert product["category_slug"] == "sensors-extra"


def test_public_inventory_filters_by_category_slug(api_client, public_makerspace):
    sensors = Category.objects.create(
        makerspace=public_makerspace,
        name="Sensors",
        slug="sensors-extra",
    )
    accessories = Category.objects.create(
        makerspace=public_makerspace,
        name="Accessories",
        slug="accessories-extra",
    )
    create_product(public_makerspace, name="Distance Sensor", category=sensors)
    create_product(public_makerspace, name="USB Cable", category=accessories)

    response = api_client.get(
        public_inventory_url(public_makerspace),
        {"category": "sensors-extra"},
    )

    assert response.status_code == 200
    assert [product["name"] for product in response.data["results"]] == [
        "Distance Sensor"
    ]


def test_public_inventory_sorts_by_most_used(api_client, public_makerspace):
    create_product(
        public_makerspace,
        name="Low Use",
        total_quantity=5,
        issued_quantity=1,
    )
    create_product(
        public_makerspace,
        name="High Use",
        total_quantity=10,
        issued_quantity=7,
    )

    response = api_client.get(
        public_inventory_url(public_makerspace),
        {"sort": "most_used"},
    )

    assert response.status_code == 200
    assert [product["name"] for product in response.data["results"]] == [
        "High Use",
        "Low Use",
    ]


def test_public_inventory_sorts_by_popular(api_client, public_makerspace):
    from apps.accounts.models import User
    from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem

    requester = User.objects.create_user(username="requester")
    request = HardwareRequest.objects.create(
        makerspace=public_makerspace,
        requester=requester,
        requester_username=requester.username,
    )
    less_popular = create_product(public_makerspace, name="Less Popular")
    more_popular = create_product(public_makerspace, name="More Popular")
    HardwareRequestItem.objects.create(
        request=request,
        product=less_popular,
        requested_quantity=1,
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=more_popular,
        requested_quantity=1,
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=more_popular,
        requested_quantity=1,
    )

    response = api_client.get(
        public_inventory_url(public_makerspace),
        {"sort": "popular"},
    )

    assert response.status_code == 200
    assert [product["name"] for product in response.data["results"]] == [
        "More Popular",
        "Less Popular",
    ]


def test_public_categories_endpoint_returns_non_empty_public_categories(
    api_client,
    public_makerspace,
):
    visible = Category.objects.create(
        makerspace=public_makerspace,
        name="Sensors",
        slug="sensors-extra",
        display_order=2,
        icon="sensors",
    )
    private_only = Category.objects.create(
        makerspace=public_makerspace,
        name="Private",
        slug="private-extra",
        display_order=1,
    )
    Category.objects.create(
        makerspace=public_makerspace,
        name="Empty",
        slug="empty-extra",
        display_order=0,
    )
    create_product(public_makerspace, name="Distance Sensor", category=visible)
    create_product(
        public_makerspace,
        name="Internal Sensor",
        category=private_only,
        is_public=False,
    )

    response = api_client.get(public_inventory_categories_url(public_makerspace))

    assert response.status_code == 200
    assert response.data == [
        {
            "id": visible.id,
            "name": "Sensors",
            "slug": "sensors-extra",
            "display_order": 2,
            "icon": "sensors",
            "product_count": 1,
        }
    ]


def test_product_clean_rejects_category_from_other_makerspace(public_makerspace):
    other = Makerspace.objects.create(name="Other Lab", slug="other-lab")
    category = Category.objects.create(
        makerspace=other,
        name="Sensors",
        slug="sensors-extra",
    )
    product = InventoryProduct(
        makerspace=public_makerspace,
        name="Distance Sensor",
        category=category,
    )

    with pytest.raises(ValidationError) as exc_info:
        product.full_clean()

    assert exc_info.value.message_dict["category"] == [
        "Category must belong to the same makerspace."
    ]


