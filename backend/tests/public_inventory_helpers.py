import hashlib


import hmac


import pytest


from django.core.exceptions import ValidationError


from django.urls import reverse


from django.utils import timezone


from rest_framework.test import APIClient


from apps.inventory.models import Category, InventoryProduct, PublicAvailabilityMode


from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


PUBLIC_PRODUCT_FIELDS = {
    "id",
    "name",
    "description",
    "category_id",
    "category_name",
    "category_slug",
    "availability",
    "image_url",
    "borrowing_terms",
}


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def public_makerspace():
    return Makerspace.objects.create(
        name="Public Lab",
        slug="public-lab",
        public_inventory_enabled=True,
    )


def public_inventory_url(makerspace):
    return reverse(
        "public-inventory",
        kwargs={"makerspace_slug": makerspace.slug},
    )


def public_inventory_code_url(makerspace):
    return reverse(
        "public-inventory",
        kwargs={"makerspace_slug": makerspace.public_code},
    )


def public_inventory_categories_url(makerspace):
    return reverse(
        "public-inventory-categories",
        kwargs={"makerspace_slug": makerspace.slug},
    )


def signed_headers(path, client_id="web-client", secret="shared-secret", timestamp=None):
    timestamp = timestamp or str(int(timezone.now().timestamp()))
    message = "\n".join(["GET", path, timestamp, ""]).encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
    }


def create_product(makerspace, name="Soldering Iron", **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": name,
        "description": f"{name} description",
        "is_public": True,
        "is_archived": False,
        "public_availability_mode": PublicAvailabilityMode.STATUS_ONLY,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def public_makerspaces_url():
    return reverse("public-makerspaces")


def get_single_product(api_client, makerspace):
    response = api_client.get(public_inventory_url(makerspace))

    assert response.status_code == 200
    assert set(response.data) == {"count", "next", "previous", "results"}
    assert response.data["count"] == 1

    return response.data["results"][0]


