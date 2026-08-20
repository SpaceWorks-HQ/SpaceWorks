import hashlib
import hmac
import time

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.apiclients.admin import ApiClientAdmin
from apps.apiclients.models import ApiClient
from apps.makerspaces.admin import MakerspaceAdmin
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _guard_v1_public(settings):
    # Container env pins HMAC_PROTECTED_PATH_PREFIXES to only /api/public/; the middleware
    # tests hit /api/v1/public/, so make the guarded-prefix list deterministic here.
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]


def test_issue_returns_raw_secret_and_stores_it_encrypted():
    s = Makerspace.objects.create(name="Kochi", slug="kochi")
    client, raw = ApiClient.issue(
        label="Kochi public", makerspace=s, allowed_origins=["http://localhost:5000"],
        scopes=["public:read"],
    )
    assert client.client_id.startswith("ck_")
    assert client.get_secret() == raw                 # round-trips
    assert bytes(client.secret_encrypted) != raw.encode()  # NOT plaintext at rest


def _admin_user(username, role=User.Role.SPACE_MANAGER, **kwargs):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@e.com", role=role, **kwargs
    )


def test_api_client_admin_changelist_is_superadmin_only():
    a = Makerspace.objects.create(name="A", slug="a")
    b = Makerspace.objects.create(name="B", slug="b")
    ApiClient.issue(
        label="A-client", makerspace=a, allowed_origins=["https://a.example.com"],
        scopes=["public:read"],
    )
    ApiClient.issue(
        label="B-client", makerspace=b, allowed_origins=["https://b.example.com"],
        scopes=["public:read"],
    )
    manager = _admin_user(
        "api-client-manager",
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
    )
    superadmin = _admin_user(
        "api-client-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    MakerspaceMembership.objects.create(
        user=manager,
        makerspace=a,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    url = reverse("admin:apiclients_apiclient_changelist")

    client = Client()
    client.force_login(manager)
    assert client.get(url).status_code == 403

    client.force_login(superadmin)
    assert client.get(url).status_code == 200


def test_integration_fields_live_on_api_client_admin_not_makerspace_admin():
    makerspace_admin = MakerspaceAdmin(Makerspace, AdminSite())
    makerspace_fields = {
        field
        for _title, options in makerspace_admin.fieldsets
        for field in options["fields"]
    }
    api_client_admin = ApiClientAdmin(ApiClient, AdminSite())

    assert "public_api_key" not in makerspace_fields
    assert "cors_allowed_origins" not in makerspace_fields
    assert "telegram_bot_token" not in makerspace_fields
    assert "smtp_password" not in makerspace_fields
    assert "makerspace_public_api_key" in api_client_admin.fields
    assert "telegram_bot_token" in api_client_admin.fields
    assert "smtp_password" in api_client_admin.fields


PUBLIC = "/api/v1/public/makerspaces/"


def _sign(client_obj, raw_secret, path, origin):
    ts = str(int(time.time()))
    msg = b"\n".join([b"GET", path.encode(), ts.encode(), b""])
    sig = hmac.new(raw_secret.encode(), msg, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": client_obj.client_id,
        "HTTP_X_TIMESTAMP": ts,
        "HTTP_X_SIGNATURE": sig,
        "HTTP_ORIGIN": origin,
    }


@override_settings(API_CLIENT_AUTH_REQUIRED=True)
def test_valid_signed_client_passes():
    obj, raw = ApiClient.issue(label="ok", allowed_origins=["http://localhost:5000"], scopes=["public:read"])
    resp = APIClient().get(PUBLIC, **_sign(obj, raw, PUBLIC, "http://localhost:5000"))
    assert resp.status_code == 200


@override_settings(API_CLIENT_AUTH_REQUIRED=True)
def test_unknown_client_rejected():
    resp = APIClient().get(PUBLIC, HTTP_X_CLIENT_ID="ck_nope", HTTP_X_TIMESTAMP="1",
                           HTTP_X_SIGNATURE="x", HTTP_ORIGIN="http://localhost:5000")
    assert resp.status_code == 401


@override_settings(API_CLIENT_AUTH_REQUIRED=True)
def test_disallowed_origin_rejected():
    obj, raw = ApiClient.issue(label="ok2", allowed_origins=["http://localhost:5000"], scopes=["public:read"])
    resp = APIClient().get(PUBLIC, **_sign(obj, raw, PUBLIC, "https://evil.test"))
    assert resp.status_code == 401


@override_settings(API_CLIENT_AUTH_REQUIRED=True)
def test_inactive_client_rejected():
    obj, raw = ApiClient.issue(label="off", allowed_origins=["http://localhost:5000"], scopes=["public:read"])
    obj.is_active = False
    obj.save()
    resp = APIClient().get(PUBLIC, **_sign(obj, raw, PUBLIC, "http://localhost:5000"))
    assert resp.status_code == 401


def test_auth_not_required_lets_public_through():
    # Default API_CLIENT_AUTH_REQUIRED=False -> unsigned public request still works.
    Makerspace.objects.create(name="Open", slug="open", public_inventory_enabled=True)
    assert APIClient().get(PUBLIC).status_code == 200
