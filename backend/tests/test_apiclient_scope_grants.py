from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
from django.db import close_old_connections

from apps.accounts.models import User
from apps.admin_api.api_client_serializers import ApiClientSerializer
from apps.apiclients.models import ApiClient
from apps.apiclients.scope_grants import TENANT_GRANTABLE_SCOPES
from apps.apiclients.scope_registry import SCOPE_VOCABULARY
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from tests.handout_roles import make_handout_member
from tests.return_helpers import authenticated_client, make_member, make_space, make_user


pytestmark = pytest.mark.django_db
ORIGIN = "https://scope-picker.example"


def _payload(scopes):
    return {"label": "Scoped client", "allowed_origins": [ORIGIN], "scopes": scopes}


def _create(actor, makerspace, scopes, **extra):
    return authenticated_client(actor).post(
        f"/api/v1/admin/makerspace/{makerspace.pk}/api-clients",
        {**_payload(scopes), **extra},
        format="json",
    )


@pytest.mark.parametrize(
    "scopes",
    [["public:read"], ["public:write"], ["public:read", "public:write"]],
)
def test_tenant_can_create_with_exact_public_scopes(scopes):
    makerspace = make_space(f"tenant-grants-{'-'.join(scopes)}")
    response = _create(make_member("tenant-grant-manager", makerspace), makerspace, scopes)

    assert response.status_code == 201
    assert response.data["scopes"] == scopes
    assert ApiClient.objects.get(pk=response.data["id"]).scopes == scopes


@pytest.mark.parametrize(
    "scopes",
    [[], ["unknown:scope"], ["public:read", "public:read"], ["public:*"],
     ["admin:read"], ["admin:write"], ["admin:*"], ["reports:read"], ["legacy:v1"]],
)
def test_tenant_scope_grants_fail_closed(scopes):
    makerspace = make_space("tenant-denied")
    response = _create(make_member("tenant-denied-manager", makerspace), makerspace, scopes)

    assert response.status_code == 400
    assert "scopes" in response.data
    assert not ApiClient.objects.exists()


def test_superadmin_can_grant_the_full_scope_vocabulary():
    makerspace = make_space("superadmin-full-vocabulary")
    actor = make_user(
        "scope-superadmin", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_superuser=True,
    )
    scopes = sorted(SCOPE_VOCABULARY)

    response = _create(actor, makerspace, scopes, client_type="server")

    assert response.status_code == 201
    assert response.data["scopes"] == scopes


def test_hidden_space_superadmin_is_tenant_limited():
    makerspace = make_space("hidden-superadmin-grants")
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    actor = make_user(
        "hidden-scope-superadmin", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_superuser=True,
    )
    MakerspaceMembership.objects.create(
        user=actor, makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )

    allowed = _create(actor, makerspace, ["public:read"], rate_limit_tier="trusted")
    denied = _create(actor, makerspace, ["legacy:v1"])
    catalog = authenticated_client(actor).get(
        f"/api/v1/admin/makerspace/{makerspace.pk}/api-client-scopes"
    )

    assert allowed.status_code == 201
    assert allowed.data["rate_limit_tier"] == "standard"
    assert denied.status_code == 400
    assert catalog.status_code == 200
    assert {row["value"] for row in catalog.data if row["grantable"]} == TENANT_GRANTABLE_SCOPES


def test_catalog_returns_grantability_and_lock_reasons():
    makerspace = make_space("tenant-scope-catalog")
    manager = make_member("catalog-manager", makerspace)
    response = authenticated_client(manager).get(
        f"/api/v1/admin/makerspace/{makerspace.pk}/api-client-scopes"
    )

    assert response.status_code == 200
    by_value = {row["value"]: row for row in response.data}
    assert set(by_value) == SCOPE_VOCABULARY
    assert {value for value, row in by_value.items() if row["grantable"]} == TENANT_GRANTABLE_SCOPES
    assert all(by_value[value]["lock_reason"] is None for value in TENANT_GRANTABLE_SCOPES)
    assert all(by_value[value]["lock_reason"] for value in SCOPE_VOCABULARY - TENANT_GRANTABLE_SCOPES)

    superadmin = make_user(
        "catalog-superadmin", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_superuser=True,
    )
    privileged = authenticated_client(superadmin).get(
        f"/api/v1/admin/makerspace/{makerspace.pk}/api-client-scopes"
    )
    assert privileged.status_code == 200
    assert all(row["grantable"] for row in privileged.data)
    assert all(row["lock_reason"] is None for row in privileged.data)


def _operation(client, operation, makerspace, api_client):
    list_url = f"/api/v1/admin/makerspace/{makerspace.pk}/api-clients"
    detail_url = f"/api/v1/admin/api-clients/{api_client.pk}"
    if operation == "list":
        return client.get(list_url)
    if operation == "create":
        return client.post(list_url, _payload(["public:read"]), format="json")
    if operation == "detail":
        return client.get(detail_url)
    if operation == "patch":
        return client.patch(detail_url, {"scopes": ["public:write"]}, format="json")
    if operation == "delete":
        return client.delete(detail_url)
    if operation == "rotate":
        return client.post(f"{detail_url}/rotate-secret", format="json")
    return client.get(f"/api/v1/admin/makerspace/{makerspace.pk}/api-client-scopes")


@pytest.mark.parametrize(
    "operation", ["list", "create", "detail", "patch", "delete", "rotate", "catalog"]
)
def test_api_client_paths_hide_invisible_tenants(operation):
    makerspace = make_space(f"invisible-target-{operation}")
    other = make_space(f"invisible-actor-{operation}")
    actor = make_member(f"invisible-manager-{operation}", other)
    api_client, _ = ApiClient.issue(
        label="Invisible", makerspace=makerspace, allowed_origins=[ORIGIN],
        scopes=["public:read"],
    )

    assert _operation(authenticated_client(actor), operation, makerspace, api_client).status_code == 404


@pytest.mark.parametrize(
    "operation", ["list", "create", "detail", "patch", "delete", "rotate", "catalog"]
)
def test_api_client_paths_forbid_visible_underprivileged_staff(operation):
    makerspace = make_space(f"visible-target-{operation}")
    actor = make_handout_member(f"visible-staff-{operation}", makerspace)
    api_client, _ = ApiClient.issue(
        label="Visible", makerspace=makerspace, allowed_origins=[ORIGIN],
        scopes=["public:read"],
    )

    assert _operation(authenticated_client(actor), operation, makerspace, api_client).status_code == 403


def test_scope_audit_metadata_records_create_and_real_changes_only():
    makerspace = make_space("scope-audit")
    manager = make_member("scope-audit-manager", makerspace)
    created = _create(manager, makerspace, ["public:read"])
    url = f"/api/v1/admin/api-clients/{created.data['id']}"
    client = authenticated_client(manager)

    unchanged = client.patch(url, {"scopes": ["public:read"]}, format="json")
    changed = client.patch(url, {"scopes": ["public:write"]}, format="json")

    assert created.status_code == 201
    assert unchanged.status_code == changed.status_code == 200
    assert AuditLog.objects.get(action="api_client.created").meta["scopes"] == ["public:read"]
    audits = AuditLog.objects.filter(action="api_client.scopes_changed")
    assert audits.count() == 1
    assert audits.get().meta == {
        "previous_scopes": ["public:read"], "scopes": ["public:write"],
    }


@pytest.mark.django_db(transaction=True)
def test_concurrent_scope_changes_lock_and_serialize(monkeypatch):
    makerspace = make_space("scope-lock")
    manager = make_member("scope-lock-manager", makerspace)
    api_client, _ = ApiClient.issue(
        label="Locked", makerspace=makerspace, allowed_origins=[ORIGIN],
        scopes=["public:read"],
    )
    first_locked, release_first = Event(), Event()
    original_update = ApiClientSerializer.update

    def hold_first(serializer, instance, validated_data):
        if validated_data.get("scopes") == ["public:write"]:
            first_locked.set()
            assert release_first.wait(timeout=5)
        return original_update(serializer, instance, validated_data)

    monkeypatch.setattr(ApiClientSerializer, "update", hold_first)

    def patch(scopes):
        close_old_connections()
        try:
            return authenticated_client(User.objects.get(pk=manager.pk)).patch(
                f"/api/v1/admin/api-clients/{api_client.pk}", {"scopes": scopes},
                format="json",
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(patch, ["public:write"])
        assert first_locked.wait(timeout=5)
        second = pool.submit(patch, ["public:read", "public:write"])
        with pytest.raises(TimeoutError):
            second.result(timeout=0.1)
        release_first.set()
        assert first.result(timeout=5) == second.result(timeout=5) == 200

    changes = list(
        AuditLog.objects.filter(action="api_client.scopes_changed")
        .order_by("created_at").values_list("meta", flat=True)
    )
    assert changes == [
        {"previous_scopes": ["public:read"], "scopes": ["public:write"]},
        {"previous_scopes": ["public:write"], "scopes": ["public:read", "public:write"]},
    ]
