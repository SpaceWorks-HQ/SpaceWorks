import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import MakerspaceArchiveRecipient
from apps.integrations.models import PlatformEmailSettings
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_product,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db


def make_superadmin(username, **kwargs):
    defaults = {
        "role": User.Role.SUPERADMIN,
        "access_status": User.AccessStatus.ACTIVE,
    }
    defaults.update(kwargs)
    return make_user(username, **defaults)


def hide_makerspace(makerspace):
    if not makerspace.memberships.filter(
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    ).exists():
        manager = make_user(
            f"{makerspace.slug}-setup-manager",
            role=User.Role.SPACE_MANAGER,
            access_status=User.AccessStatus.ACTIVE,
        )
        MakerspaceMembership.objects.create(
            user=manager,
            makerspace=makerspace,
            role=MakerspaceMembership.Role.SPACE_MANAGER,
        )
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])


def test_superadmin_keeps_setup_access_for_enabled_space_without_manager():
    setup_space = make_space("hard-hide-setup-window")
    superadmin = make_superadmin("hard-hide-setup-window-super")

    assert rbac.can(superadmin, rbac.Action.MANAGE_MAKERSPACE, setup_space.id) is True
    assert rbac.can(superadmin, rbac.Action.EDIT_INVENTORY, setup_space.id) is True
    assert rbac.resolve_scope(superadmin) is rbac.ALL


def test_superadmin_access_off_blocks_even_without_space_manager():
    setup_space = make_space("hard-hide-off-without-manager")
    setup_space.superadmin_access_enabled = False
    setup_space.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_superadmin("hard-hide-off-without-manager-super")

    assert rbac.can(superadmin, rbac.Action.MANAGE_MAKERSPACE, setup_space.id) is False
    assert rbac.can(superadmin, rbac.Action.EDIT_INVENTORY, setup_space.id) is False
    assert setup_space.id not in rbac.resolve_scope(superadmin)


def test_superadmin_rbac_hard_hides_disabled_makerspace():
    hidden = make_space("hard-hide-rbac-hidden")
    hide_makerspace(hidden)
    visible = make_space("hard-hide-rbac-visible")
    superadmin = make_superadmin("hard-hide-rbac-super")
    hidden_product = make_product(hidden, name="Hidden probe")
    visible_product = make_product(visible, name="Visible probe")

    for action in (
        rbac.Action.VIEW_INVENTORY,
        rbac.Action.MANAGE_PRINTING,
        rbac.Action.EDIT_INVENTORY,
    ):
        assert rbac.can(superadmin, action, hidden.id) is False
        assert rbac.can(superadmin, action, visible.id) is True

    view_scope = rbac.makerspaces_for_action(
        superadmin,
        rbac.Action.VIEW_INVENTORY,
    )
    assert view_scope is not rbac.ALL
    assert hidden.id not in view_scope
    assert visible.id in view_scope
    assert rbac.makerspaces_for_actions(
        superadmin,
        rbac.Action.VIEW_INVENTORY,
        rbac.Action.MANAGE_PRINTING,
    ) == view_scope

    scoped_products = rbac.scope_by_action(
        superadmin,
        rbac.Action.VIEW_INVENTORY,
        InventoryProduct.objects.all(),
    )
    assert hidden_product not in scoped_products
    assert visible_product in scoped_products

    resolved = rbac.resolve_scope(superadmin)
    assert resolved is not rbac.ALL
    assert hidden.id not in resolved
    assert visible.id in resolved

    scoped_spaces = rbac.scope_by_makerspace(
        superadmin,
        Makerspace.objects.all(),
        makerspace_field="id",
    )
    assert hidden not in scoped_spaces
    assert visible in scoped_spaces


def test_superadmin_hidden_checks_accept_string_makerspace_ids():
    hidden = make_space("hard-hide-string-id")
    hide_makerspace(hidden)
    superadmin = make_superadmin("hard-hide-string-id-super")
    makerspace_id = str(hidden.id)

    assert (
        rbac.can(superadmin, rbac.Action.EDIT_INVENTORY, makerspace_id)
        is False
    )
    assert (
        rbac.superadmin_hidden_block_applies(
            superadmin,
            makerspace_id,
            rbac.Action.EDIT_INVENTORY,
        )
        is True
    )


def test_superadmin_rbac_preserves_all_fast_path_when_no_makerspace_is_hidden():
    superadmin = make_superadmin("hard-hide-fast-path-super")
    make_space("hard-hide-fast-path-visible")

    assert (
        rbac.makerspaces_for_action(superadmin, rbac.Action.VIEW_INVENTORY)
        is rbac.ALL
    )
    assert (
        rbac.makerspaces_for_actions(
            superadmin,
            rbac.Action.VIEW_INVENTORY,
            rbac.Action.MANAGE_PRINTING,
        )
        is rbac.ALL
    )
    assert rbac.resolve_scope(superadmin) is rbac.ALL


def test_superadmin_explicit_hidden_member_gets_membership_role_only():
    hidden = make_space("hard-hide-member-print")
    hide_makerspace(hidden)
    visible = make_space("hard-hide-member-visible")
    superadmin = make_superadmin("hard-hide-member-super")
    MakerspaceMembership.objects.create(
        user=superadmin,
        makerspace=hidden,
        role=MakerspaceMembership.Role.PRINT_MANAGER,
    )

    assert rbac.can(superadmin, rbac.Action.MANAGE_PRINTING, hidden.id) is True
    assert rbac.can(superadmin, rbac.Action.MANAGE_MAKERSPACE, hidden.id) is False
    assert rbac.can(superadmin, rbac.Action.EDIT_INVENTORY, hidden.id) is False
    assert rbac.can(superadmin, rbac.Action.MANAGE_MAKERSPACE, visible.id) is True


def test_hidden_makerspace_member_keeps_manage_access_and_inventory_visibility():
    hidden = make_space("hard-hide-own-member")
    hide_makerspace(hidden)
    space_manager = make_member(
        "hard-hide-own-manager",
        hidden,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
        role=User.Role.SPACE_MANAGER,
    )
    product = make_product(hidden, name="Hidden member product")

    assert (
        rbac.can(space_manager, rbac.Action.MANAGE_MAKERSPACE, hidden.id)
        is True
    )
    assert list(
        rbac.scope_by_action(
            space_manager,
            rbac.Action.VIEW_INVENTORY,
            InventoryProduct.objects.all(),
        )
    ) == [product]

    response = authenticated_client(space_manager).get(
        reverse("admin-inventory", kwargs={"makerspace_id": hidden.id})
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.data["results"]] == [product.id]


def test_superadmin_inventory_endpoint_is_blocked_for_hidden_space_but_visible_works():
    hidden = make_space("hard-hide-api-hidden")
    hide_makerspace(hidden)
    visible = make_space("hard-hide-api-visible")
    hidden_product = make_product(hidden, name="Hidden endpoint product")
    visible_product = make_product(visible, name="Visible endpoint product")
    superadmin = make_superadmin("hard-hide-api-super")
    client = authenticated_client(superadmin)

    hidden_list = client.get(
        reverse("admin-inventory", kwargs={"makerspace_id": hidden.id})
    )
    visible_list = client.get(
        reverse("admin-inventory", kwargs={"makerspace_id": visible.id})
    )
    hidden_detail = client.get(
        reverse("admin-inventory-detail", kwargs={"pk": hidden_product.id})
    )

    assert hidden_list.status_code == 403
    assert hidden_detail.status_code == 404
    assert visible_list.status_code == 200
    assert [item["id"] for item in visible_list.data["results"]] == [
        visible_product.id
    ]


def test_staff_makerspace_api_excludes_hidden_space_for_superadmin():
    hidden = make_space("hard-hide-visible-hidden")
    hide_makerspace(hidden)
    visible = make_space("hard-hide-visible-enabled")
    superadmin = make_superadmin("hard-hide-visible-super")
    client = authenticated_client(superadmin)

    listed = client.get(reverse("admin-makerspaces"))
    detail = client.get(reverse("admin-makerspace", kwargs={"pk": hidden.id}))

    assert listed.status_code == 200
    rows = {row["id"]: row for row in listed.data}
    assert hidden.id not in rows
    assert visible.id in rows
    assert "public_api_key" in rows[visible.id]

    assert detail.status_code == 404


def test_superadmin_break_glass_create_is_space_manager_only_and_fresh_user_only():
    hidden = make_space("hard-hide-break-glass")
    hide_makerspace(hidden)
    existing = make_user(
        "hard-hide-existing-user",
        access_status=User.AccessStatus.ACTIVE,
    )
    superadmin = make_superadmin("hard-hide-break-glass-super")
    client = authenticated_client(superadmin)

    created = client.post(
        reverse("admin-users-space-managers"),
        {
            "username": "hard-hide-new-manager",
            "email": "hard-hide-new-manager@example.com",
            "makerspace_id": hidden.id,
            "role": MakerspaceMembership.Role.SPACE_MANAGER,
        },
        format="json",
    )
    # Any non-Space-Manager role proves the break-glass rule; Machine Manager rather than
    # the retired Print Manager, whose fixed-role route no longer exists.
    rejected_role = client.post(
        reverse("admin-users-machine-managers"),
        {
            "username": "hard-hide-new-machine",
            "email": "hard-hide-new-machine@example.com",
            "makerspace_id": hidden.id,
            "role": MakerspaceMembership.Role.MACHINE_MANAGER,
        },
        format="json",
    )
    rejected_existing = client.post(
        reverse("admin-users-space-managers"),
        {
            "username": existing.username,
            "email": "hard-hide-existing-user-new@example.com",
            "makerspace_id": hidden.id,
            "role": MakerspaceMembership.Role.SPACE_MANAGER,
        },
        format="json",
    )

    assert created.status_code == 201
    created_user = User.objects.get(username="hard-hide-new-manager")
    assert created.data["makerspace_id"] == hidden.id
    assert created.data["role"] == MakerspaceMembership.Role.SPACE_MANAGER
    assert created_user.role == User.Role.SPACE_MANAGER
    assert AuditLog.objects.filter(
        action="superadmin.break_glass_space_manager_created",
        makerspace=hidden,
        target_id=str(created_user.id),
    ).exists()

    assert rejected_role.status_code == 403
    assert not User.objects.filter(username="hard-hide-new-print").exists()
    assert rejected_existing.status_code == 400
    assert "username" in rejected_existing.data
    assert not MakerspaceMembership.objects.filter(
        user=existing,
        makerspace=hidden,
    ).exists()


def test_staff_create_rejects_weak_supplied_password():
    makerspace = make_space("hard-hide-weak-password")
    superadmin = make_superadmin("hard-hide-weak-password-super")
    client = authenticated_client(superadmin)

    response = client.post(
        reverse("admin-users-machine-managers"),
        {
            "username": "hard-hide-weak-password-user",
            "email": "hard-hide-weak-password-user@example.com",
            "makerspace_id": makerspace.id,
            "role": MakerspaceMembership.Role.MACHINE_MANAGER,
            "password": "123",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "password" in response.data
    assert not User.objects.filter(
        username="hard-hide-weak-password-user",
    ).exists()


def test_superadmin_access_cannot_be_disabled_until_platform_smtp_is_configured():
    makerspace = make_space("hard-hide-smtp-block")
    superadmin = make_superadmin("hard-hide-smtp-super")
    client = authenticated_client(superadmin)
    url = reverse("admin-makerspace", kwargs={"pk": makerspace.id})

    blocked = client.patch(
        url,
        {"superadmin_access_enabled": False},
        format="json",
    )
    makerspace.refresh_from_db()
    assert blocked.status_code == 400
    assert makerspace.superadmin_access_enabled is True

    cfg = PlatformEmailSettings.load()
    cfg.smtp_host = "smtp.example.com"
    cfg.save(update_fields=["smtp_host"])

    # The recipient floor is a SECOND, independent precondition. Assert it blocks on
    # its own so this test keeps proving what it is named for -- that the SMTP gate
    # opens -- rather than passing because some other guard happens to refuse.
    floor_blocked = client.patch(
        url,
        {"superadmin_access_enabled": False},
        format="json",
    )
    makerspace.refresh_from_db()
    assert floor_blocked.status_code == 400
    assert makerspace.superadmin_access_enabled is True

    for number in (1, 2):
        MakerspaceArchiveRecipient.objects.create(
            makerspace=makerspace,
            public_recipient=f"age1hardhidesmtp{number}",
            fingerprint=f"{number:064x}",
            label=f"Custodian {number}",
            verified_at=timezone.now(),
        )

    allowed = client.patch(
        url,
        {"superadmin_access_enabled": False},
        format="json",
    )
    makerspace.refresh_from_db()
    assert allowed.status_code == 200
    assert makerspace.superadmin_access_enabled is False


def test_django_admin_object_permissions_keep_hidden_makerspace_audit_only():
    hidden = make_space("hard-hide-control-hidden")
    hide_makerspace(hidden)
    visible = make_space("hard-hide-control-visible")
    hidden_product = make_product(hidden, name="Hidden control product")
    visible_product = make_product(visible, name="Visible control product")
    superadmin = make_superadmin(
        "hard-hide-control-super",
        is_staff=True,
        is_superuser=True,
    )
    request = RequestFactory().get("/control/")
    request.user = superadmin

    product_admin = admin.site._registry[InventoryProduct]
    makerspace_admin = admin.site._registry[Makerspace]

    assert product_admin.has_view_permission(request, hidden_product) is False
    assert product_admin.has_change_permission(request, hidden_product) is False
    assert makerspace_admin.has_view_permission(request, hidden) is False
    assert makerspace_admin.has_change_permission(request, hidden) is False
    assert makerspace_admin.has_delete_permission(request, hidden) is False
    assert makerspace_admin.get_inline_instances(request, hidden) == []

    assert product_admin.has_view_permission(request, visible_product) is True
    assert product_admin.has_change_permission(request, visible_product) is True
    assert makerspace_admin.has_view_permission(request, visible) is True
    assert makerspace_admin.has_change_permission(request, visible) is True
