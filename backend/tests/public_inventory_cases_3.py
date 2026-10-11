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

def test_frontend_api_client_allows_matching_origin_and_makerspace_code(
    settings,
    api_client,
    public_makerspace,
):
    from apps.apiclients.models import ApiClient

    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/"]
    ApiClient.issue(
        label="frontend",
        makerspace=public_makerspace,
        allowed_origins=["https://lab.example.com"],
        scopes=["public:read"],
    )
    client = public_makerspace.api_clients.get()
    create_product(public_makerspace)

    response = api_client.get(
        public_inventory_code_url(public_makerspace),
        HTTP_X_CLIENT_ID=client.client_id,
        HTTP_ORIGIN="https://lab.example.com",
    )

    assert response.status_code == 200


def test_frontend_api_client_rejects_other_makerspace_code(
    settings,
    api_client,
    public_makerspace,
):
    from apps.apiclients.models import ApiClient

    other = Makerspace.objects.create(
        name="Other Lab",
        slug="other-lab",
        public_inventory_enabled=True,
    )
    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/"]
    client, _secret = ApiClient.issue(
        label="frontend",
        makerspace=public_makerspace,
        allowed_origins=["https://lab.example.com"],
        scopes=["public:read"],
    )

    response = api_client.get(
        public_inventory_code_url(other),
        HTTP_X_CLIENT_ID=client.client_id,
        HTTP_ORIGIN="https://lab.example.com",
    )

    assert response.status_code == 401


@pytest.mark.parametrize("invalid_signature_case", ["missing", "wrong-client", "wrong-secret"])
def test_hmac_rejects_unsigned_or_invalid_public_inventory_request(
    settings,
    api_client,
    public_makerspace,
    invalid_signature_case,
):
    from apps.apiclients.models import ApiClient

    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.HMAC_MAX_CLOCK_SKEW_SECONDS = 300
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/"]
    client, secret = ApiClient.issue(label="web", allowed_origins=["http://testserver"], scopes=["public:read"])
    create_product(public_makerspace)
    path = public_inventory_url(public_makerspace)

    headers = {}
    if invalid_signature_case == "wrong-client":
        headers = signed_headers(path, client_id="ck_wrong", secret=secret)
    if invalid_signature_case == "wrong-secret":
        headers = signed_headers(path, client_id=client.client_id, secret="wrong-secret")
    if headers:
        headers["HTTP_ORIGIN"] = "http://testserver"

    response = api_client.get(path, **headers)

    assert response.status_code == 401


def test_openapi_schema_includes_public_inventory_path(api_client):
    response = api_client.get(reverse("schema"))

    assert response.status_code == 200
    schema_text = response.content.decode()
    assert "public/" in schema_text
    assert "inventory" in schema_text


def test_backend_docs_are_available_at_root_and_api_docs_alias(api_client):
    root = api_client.get("/")
    assert root.status_code == 200
    assert b"/docs/" in root.content
    assert b"/redoc/" in root.content
    assert b"window.location.hash" in root.content

    docs = api_client.get("/docs/")
    assert docs.status_code == 200
    assert b"swagger" in docs.content.lower()

    redoc = api_client.get("/redoc/")
    assert redoc.status_code == 200
    assert b"redoc" in redoc.content.lower()

    assert api_client.get("/schema/").status_code == 200
    assert api_client.get("/api/docs/").status_code == 200
    assert api_client.get("/api/schema/").status_code == 404


