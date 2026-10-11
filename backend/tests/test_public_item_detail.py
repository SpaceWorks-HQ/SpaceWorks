"""Public deep-link detail must have exactly the catalogue's exposure contract."""

import pytest
from rest_framework.test import APIClient

from apps.inventory.serializers import PublicProductSerializer
from apps.makerspaces.models import Makerspace
from tests.return_helpers import make_product, make_space

pytestmark = pytest.mark.django_db


def detail_url(space, product_id):
    return f"/api/v1/public/{space.slug}/inventory/{product_id}/"


@pytest.mark.parametrize(
    "mode,show_count,expected",
    [
        ("hidden", True, None),
        ("hidden", False, None),
        ("status_only", True, {"mode": "status_only", "label": "Available"}),
        ("status_only", False, {"mode": "status_only", "label": "Available"}),
        ("exact_count", False, {"mode": "status_only", "label": "Available"}),
        ("exact_count", True, {"mode": "exact_count", "count": 10, "label": "Available"}),
    ],
)
def test_detail_matches_public_list_serializer_and_visibility(mode, show_count, expected):
    space = make_space(f"detail-{mode}-{show_count}")
    product = make_product(
        space, storage_location="Private shelf", public_availability_mode=mode,
        show_public_count=show_count,
    )
    client = APIClient()
    detail = client.get(detail_url(space, product.pk))
    listing = client.get(f"/api/v1/public/{space.slug}/inventory/")

    assert detail.status_code == 200
    assert listing.status_code == 200
    assert detail.data == listing.data["results"][0]
    assert set(detail.data) == set(PublicProductSerializer().fields)
    assert detail.data["availability"] == expected
    assert "Private shelf" not in str(detail.data)
    assert not {
        "storage_location", "box", "box_id", "qr_code", "scan_history",
        "evidence", "requester_history", "total_quantity", "available_quantity",
        "issued_quantity", "reserved_quantity",
    }.intersection(detail.data)


def test_private_archived_cross_tenant_and_missing_have_identical_404():
    space = make_space("detail-safe")
    other = make_space("detail-other")
    private = make_product(space, is_public=False)
    archived = make_product(space, is_archived=True)
    foreign = make_product(other)
    missing_id = max(private.pk, archived.pk, foreign.pk) + 1000
    responses = [APIClient().get(detail_url(space, pk)) for pk in (
        private.pk, archived.pk, foreign.pk, missing_id,
    )]

    assert all(response.status_code == 404 for response in responses)
    assert all(response.data == responses[0].data for response in responses)
    assert responses[0].data == {"detail": "Item not found."}


@pytest.mark.parametrize("suffix", ["inventory/{id}/", "inventory/", "inventory/categories/"])
def test_detail_module_off_is_400_and_reenable_restores_same_item(suffix):
    space = make_space("detail-module")
    product = make_product(space)
    original = space.enabled_modules
    space.enabled_modules = [key for key in original if key != "public_inventory"]
    space.save(update_fields=["enabled_modules"])
    client = APIClient()
    url = f"/api/v1/public/{space.slug}/" + suffix.format(id=product.pk)

    response = client.get(url)
    assert response.status_code == 400
    assert response.data == {"module": ["public_inventory is disabled for this makerspace."]}

    space.enabled_modules = original
    space.save(update_fields=["enabled_modules"])
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("module_on", [True, False])
def test_detail_disabled_public_site_and_missing_space_have_same_not_found(module_on):
    space = make_space("detail-disabled")
    product = make_product(space)
    space.public_inventory_enabled = False
    if not module_on:
        space.enabled_modules = [key for key in space.enabled_modules if key != "public_inventory"]
    space.save(update_fields=["public_inventory_enabled", "enabled_modules"])
    client = APIClient()

    disabled = client.get(detail_url(space, product.pk))
    missing = client.get(f"/api/v1/public/does-not-exist/inventory/{product.pk}/")
    assert disabled.status_code == missing.status_code == 404
    assert disabled.data == missing.data == {"detail": "Item not found."}


@pytest.mark.parametrize("lifecycle", [Makerspace.LifecycleState.IMPORTING, Makerspace.LifecycleState.ABORTED])
def test_detail_refuses_unservable_tenant(lifecycle):
    space = make_space(f"detail-{lifecycle}")
    product = make_product(space)
    Makerspace.objects.filter(pk=space.pk).update(lifecycle_state=lifecycle)
    response = APIClient().get(detail_url(space, product.pk))
    assert response.status_code == 404
    assert response.data == {"detail": "Item not found."}


def test_detail_refuses_archived_tenant():
    from django.utils import timezone

    space = make_space("detail-archived-tenant")
    product = make_product(space)
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    response = APIClient().get(detail_url(space, product.pk))
    assert response.status_code == 404
    assert response.data == {"detail": "Item not found."}


def test_detail_refuses_edition_hidden_inventory(settings):
    settings.SPACEWORKS_EDITION = "events"
    space = make_space("detail-hidden-edition")
    product = make_product(space)
    response = APIClient().get(detail_url(space, product.pk))
    assert response.status_code == 404
    assert response.data == {"detail": "Item not found."}


@pytest.mark.parametrize("query", ["vaultxyz", "-vaultxyz", "quantity"])
def test_public_search_cannot_infer_storage_location_or_tracking_mode(query):
    from apps.inventory.search import apply_q
    from apps.inventory.models import InventoryProduct

    space = make_space("detail-private-search")
    product = make_product(space, name="Cordless Drill", description="Workshop tool", storage_location="vaultxyz")
    make_product(space, name="Heat Gun", description="Workshop tool")
    url = f"/api/v1/public/{space.slug}/inventory/"
    response = APIClient().get(url, {"q": query})
    assert response.status_code == 200
    if query.startswith("-"):
        assert {row["name"] for row in response.data["results"]} == {"Cordless Drill", "Heat Gun"}
    else:
        assert response.data["results"] == []
    # The staff vector retains private-field search; only the public projection changes.
    assert apply_q(InventoryProduct.objects.filter(pk=product.pk), "vaultxyz").exists()


@pytest.mark.parametrize("query", ["drill", "worksh", '"Workshop tool"', "cordles dril"])
def test_public_search_preserves_prefix_phrase_and_typo_matching(query):
    space = make_space("detail-public-search")
    product = make_product(space, name="Cordless Drill", description="Workshop tool")
    response = APIClient().get(f"/api/v1/public/{space.slug}/inventory/", {"q": query})
    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [product.pk]


def test_public_inventory_openapi_documents_errors_and_list_shaped_module_field():
    from django.urls import path
    from drf_spectacular.generators import SchemaGenerator
    from apps.inventory.views import PublicInventoryDetailView

    schema = SchemaGenerator(patterns=[path(
        "api/v1/public/<str:makerspace_slug>/inventory/<int:pk>/",
        PublicInventoryDetailView.as_view(),
    )]).get_schema(public=True)
    operation = next(iter(schema["paths"].values()))["get"]
    assert {"200", "400", "401", "403", "404", "429"} <= set(operation["responses"])
    assert "requestBody" not in operation
    error_ref = operation["responses"]["400"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    error = schema["components"]["schemas"][error_ref]
    assert error["properties"]["module"]["type"] == "array"
    assert error["properties"]["module"]["items"]["type"] == "string"
