import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.machines.models import MachineType
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.procurement import access as procurement_access
from tests.organizations.test_org_authority import (
    grant,
    link,
    make_makerspace,
    make_organization,
    make_user,
)


pytestmark = pytest.mark.django_db

SURFACES = (
    ("roles", rbac.Action.MANAGE_MAKERSPACE),
    ("integration", rbac.Action.MANAGE_MAKERSPACE),
    ("domain", rbac.Action.MANAGE_MAKERSPACE),
    ("procurement", rbac.Action.MANAGE_PRINTING),
)


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _grant_actor(slug, makerspace, action):
    actor = make_user(f"{slug}-actor")
    organization = make_organization(f"{slug}-org")
    link(organization, makerspace, "manager")
    actions = list(action) if isinstance(action, (list, tuple, set)) else [action]
    grant(organization, actor, actions)
    return actor


def _visible_without_authority(slug, makerspace):
    actor = make_user(f"{slug}-local")
    role = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name=f"{slug} local",
        slug=f"{slug}-local",
        granted_actions=[],
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


def _url(surface, makerspace):
    names = {
        "roles": "admin-role-list-create",
        "integration": "makerspace-integration-health",
        "domain": "makerspace-verify-domain",
        "procurement": "procurement:to-buy-machine-type-options",
    }
    return reverse(names[surface], kwargs={"makerspace_id": makerspace.pk})


def _call(surface, actor, makerspace):
    client = _client(actor)
    url = _url(surface, makerspace)
    return client.post(url, HTTP_HOST="localhost") if surface == "domain" else client.get(url)


@pytest.mark.parametrize(("surface", "action"), SURFACES)
def test_converted_space_surfaces_preserve_404_vs_403(
    surface, action, monkeypatch
):
    monkeypatch.setattr(
        "apps.admin_api.views_domain_verification.verify_domain",
        lambda makerspace: (makerspace.frontend_domain_status, None, "checked"),
    )
    visible = make_makerspace(f"org-surface-{surface}")
    visible.frontend_domain = f"{surface}.example.test"
    visible.save(update_fields=["frontend_domain"])
    authorized = _grant_actor(f"{surface}-allowed", visible, action)
    underprivileged = _visible_without_authority(f"{surface}-denied", visible)
    outsider = make_user(f"{surface}-outsider")

    hidden = make_makerspace(
        f"org-surface-{surface}-hidden", superadmin_access_enabled=False
    )
    hidden_actor = _grant_actor(f"{surface}-hidden", hidden, action)
    archived = make_makerspace(f"org-surface-{surface}-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    archived_actor = _grant_actor(f"{surface}-archived", archived, action)

    assert _call(surface, authorized, visible).status_code == 200
    assert _call(surface, outsider, visible).status_code == 404
    assert _call(surface, underprivileged, visible).status_code == 403
    assert _call(surface, hidden_actor, hidden).status_code == 404
    assert _call(surface, archived_actor, archived).status_code == 404


def test_org_manager_role_crud_revalidates_locked_org_authority():
    makerspace = make_makerspace("org-role-service")
    actor = _grant_actor(
        "org-role-service",
        makerspace,
        [rbac.Action.MANAGE_MAKERSPACE, rbac.Action.VIEW_INVENTORY],
    )
    client = _client(actor)
    list_url = _url("roles", makerspace)

    created = client.post(
        list_url,
        {"name": "Organization readers", "granted_actions": ["view_inventory"]},
        format="json",
    )
    assert created.status_code == 201
    detail_url = reverse(
        "admin-role-detail",
        kwargs={"makerspace_id": makerspace.id, "role_id": created.data["id"]},
    )
    assert client.patch(
        detail_url, {"name": "Organization viewers"}, format="json"
    ).status_code == 200
    assert client.delete(detail_url).status_code == 204


def test_converted_list_surfaces_do_not_leak_cross_tenant_rows():
    target = make_makerspace("org-list-target")
    foreign = make_makerspace("org-list-foreign")
    manager = _grant_actor(
        "org-list-role", target, rbac.Action.MANAGE_MAKERSPACE
    )
    role_response = _client(manager).get(_url("roles", target))
    assert role_response.status_code == 200
    assert {row["makerspace_id"] for row in role_response.data} == {target.id}

    target_type = MachineType.objects.create(
        makerspace=target, slug="target-type", name="Target type"
    )
    foreign_type = MachineType.objects.create(
        makerspace=foreign, slug="foreign-type", name="Foreign type"
    )
    buyer = _grant_actor("org-list-procurement", target, rbac.Action.EDIT_INVENTORY)
    options = _client(buyer).get(_url("procurement", target))
    ids = {row["id"] for row in options.data["results"]}
    assert target_type.id in ids
    assert foreign_type.id not in ids


def test_org_printing_procurement_options_do_not_invent_local_machine_scope():
    makerspace = make_makerspace("org-printing-options")
    machine_type = MachineType.objects.create(
        makerspace=makerspace,
        slug="org-printing-option",
        name="Organization printing option",
    )
    actor = _grant_actor(
        "org-printing-options", makerspace, rbac.Action.MANAGE_PRINTING
    )

    assert procurement_access.machine_type_scope(actor, makerspace.id) is None
    response = _client(actor).get(_url("procurement", makerspace))
    assert response.status_code == 200
    assert machine_type.id in {row["id"] for row in response.data["results"]}


def test_org_only_grants_deliberately_do_not_open_dashboard_or_notifications():
    makerspace = make_makerspace("org-narrow-parity")
    actor = _grant_actor(
        "org-narrow-parity", makerspace, rbac.Action.VIEW_INVENTORY
    )
    client = _client(actor)

    assert client.get(
        reverse("operations-dashboard", kwargs={"makerspace_id": makerspace.id})
    ).status_code == 404
    assert client.get(
        reverse(
            "notifications:notifications-list",
            kwargs={"makerspace_id": makerspace.id},
        )
    ).status_code == 404
