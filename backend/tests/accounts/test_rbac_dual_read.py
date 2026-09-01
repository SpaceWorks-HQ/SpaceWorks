import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


pytestmark = pytest.mark.django_db


def make_user(username, **kwargs):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="password",
        **kwargs,
    )


def make_makerspace(slug, **kwargs):
    return Makerspace.objects.create(name=slug, slug=slug, **kwargs)


def seeded_role(makerspace, legacy_role):
    role = MakerspaceRole.objects.filter(
        makerspace=makerspace,
        legacy_role=legacy_role,
    ).first()
    if role is not None:
        return role
    # print_manager remains a display-only compatibility value, but B7c no
    # longer seeds a default role for it.  Give fallback tests equivalent
    # assigned authority without reinstating the retired default.
    return custom_role(
        makerspace,
        f"legacy-{legacy_role}",
        list(rbac._MEMBERSHIP_ROLE_ACTIONS[legacy_role]),
    )

def custom_role(makerspace, slug, actions):
    return MakerspaceRole.objects.create(
        makerspace=makerspace,
        name=slug.replace("-", " ").title(),
        slug=slug,
        granted_actions=actions,
        is_default=False,
        legacy_role=None,
    )


def test_action_registries_contain_the_frozen_action_vocabulary():
    # 19 since collect_service_request split job handover out of manage_machines.
    assert len(rbac.ALL_ACTIONS) == 19
    assert rbac.ROLE_FORBIDDEN_ACTIONS == {
        rbac.Action.TRANSFER_STOCK,
        rbac.Action.MANAGE_STAFF,
    }
    assert rbac.ROLE_GRANTABLE_ACTIONS == (
        rbac.ALL_ACTIONS - rbac.ROLE_FORBIDDEN_ACTIONS
    )


def test_assigned_roles_match_the_frozen_legacy_matrix():
    makerspace = make_makerspace("dual-read-assigned")
    memberships = {}
    for index, legacy_role in enumerate(rbac._MEMBERSHIP_ROLE_ACTIONS):
        membership = MakerspaceMembership.objects.create(
            makerspace=makerspace,
            user=make_user(f"assigned-default-{index}"),
            role=legacy_role,
            assigned_role=seeded_role(makerspace, legacy_role),
        )
        memberships[legacy_role] = membership

    for legacy_role, membership in memberships.items():
        expected = rbac.expand_implied_actions(set(rbac._MEMBERSHIP_ROLE_ACTIONS[legacy_role]))
        assert rbac.actions_for_membership(membership) == expected
        for action in rbac.ALL_ACTIONS:
            assert rbac.can(membership.user, action, makerspace.id) == (action in expected)


def test_null_assigned_role_falls_back_to_the_frozen_legacy_matrix():
    makerspace = make_makerspace("dual-read-fallback")
    memberships = {}
    for index, legacy_role in enumerate(rbac._MEMBERSHIP_ROLE_ACTIONS):
        membership = MakerspaceMembership.objects.create(
            makerspace=makerspace,
            user=make_user(f"fallback-default-{index}"),
            role=legacy_role,
            assigned_role=seeded_role(makerspace, legacy_role),
        )
        MakerspaceMembership.objects.filter(pk=membership.pk).update(assigned_role=None)
        memberships[legacy_role] = MakerspaceMembership.objects.get(pk=membership.pk)

    for legacy_role, membership in memberships.items():
        expected = rbac.expand_implied_actions(set(rbac._MEMBERSHIP_ROLE_ACTIONS[legacy_role]))
        assert rbac.actions_for_membership(membership) == expected
        for action in rbac.ALL_ACTIONS:
            assert rbac.can(membership.user, action, makerspace.id) == (action in expected)


def test_custom_narrow_role_controls_can_and_action_scopes():
    makerspace = make_makerspace("dual-read-narrow")
    role = custom_role(
        makerspace,
        "narrow-role",
        [rbac.Action.VIEW_INVENTORY, rbac.Action.MANAGE_EVENTS],
    )
    user = make_user("narrow-role-user")
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )

    allowed = {rbac.Action.VIEW_INVENTORY, rbac.Action.MANAGE_EVENTS}
    for action in rbac.ALL_ACTIONS:
        assert rbac.can(user, action, makerspace.id) == (action in allowed)

    assert rbac.makerspaces_for_action(user, rbac.Action.VIEW_INVENTORY) == {makerspace.id}
    assert rbac.makerspaces_for_action(user, rbac.Action.MANAGE_EVENTS) == {makerspace.id}
    assert rbac.makerspaces_for_action(user, rbac.Action.EDIT_INVENTORY) == set()
    assert rbac.makerspaces_for_actions(
        user, rbac.Action.VIEW_INVENTORY, rbac.Action.MANAGE_EVENTS
    ) == {makerspace.id}
    assert set(
        rbac.scope_by_action(
            user, rbac.Action.MANAGE_EVENTS, Makerspace.objects.all(), field="id"
        ).values_list("id", flat=True)
    ) == {makerspace.id}


def test_forbidden_and_malformed_assigned_role_actions_fail_closed():
    makerspace = make_makerspace("dual-read-forbidden")
    role = custom_role(makerspace, "corrupt-role", [rbac.Action.VIEW_INVENTORY])
    user = make_user("corrupt-role-user")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    MakerspaceRole.objects.filter(pk=role.pk).update(
        granted_actions=[
            rbac.Action.TRANSFER_STOCK,
            rbac.Action.MANAGE_STAFF,
            rbac.Action.EDIT_INVENTORY,
            "not_a_real_action",
            123,
            {"x": 1},
        ]
    )
    membership = MakerspaceMembership.objects.select_related("assigned_role").get(
        pk=membership.pk
    )

    assert rbac.actions_for_membership(membership) == {rbac.Action.EDIT_INVENTORY}
    assert not rbac.can(user, rbac.Action.TRANSFER_STOCK, makerspace.id)
    assert not rbac.can(user, rbac.Action.MANAGE_STAFF, makerspace.id)
    assert rbac.makerspaces_for_action(user, rbac.Action.TRANSFER_STOCK) == set()


def test_cross_tenant_assigned_role_fails_closed_without_legacy_fallback():
    makerspace_a = make_makerspace("dual-read-tenant-a")
    makerspace_b = make_makerspace("dual-read-tenant-b")
    user = make_user("cross-tenant-role-user")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace_a,
        user=user,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=seeded_role(makerspace_a, MakerspaceMembership.Role.SPACE_MANAGER),
    )
    foreign_role = custom_role(makerspace_b, "foreign-role", [rbac.Action.VIEW_INVENTORY])
    MakerspaceMembership.objects.filter(pk=membership.pk).update(
        assigned_role_id=foreign_role.id
    )
    membership = MakerspaceMembership.objects.select_related("assigned_role").get(
        pk=membership.pk
    )

    assert rbac.actions_for_membership(membership) == set()
    assert all(not rbac.can(user, action, makerspace_a.id) for action in rbac.ALL_ACTIONS)


def test_hard_hidden_makerspace_requires_membership_and_limits_it_to_role_actions():
    makerspace = make_makerspace(
        "dual-read-hidden", superadmin_access_enabled=False
    )
    superadmin = make_user(
        "hidden-superadmin",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
        is_staff=True,
    )

    for action in rbac.ALL_ACTIONS:
        assert not rbac.can(superadmin, action, makerspace.id)
        assert rbac.makerspaces_for_action(superadmin, action) == set()
        assert rbac.superadmin_hidden_block_applies(superadmin, makerspace.id, action)

    role = custom_role(makerspace, "hidden-narrow", [rbac.Action.MANAGE_EVENTS])
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=superadmin,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )

    assert rbac.can(superadmin, rbac.Action.MANAGE_EVENTS, makerspace.id)
    assert not rbac.can(superadmin, rbac.Action.EDIT_INVENTORY, makerspace.id)
    assert rbac.makerspaces_for_action(
        superadmin, rbac.Action.MANAGE_EVENTS
    ) is rbac.ALL
    assert rbac.makerspaces_for_action(superadmin, rbac.Action.EDIT_INVENTORY) == set()
    assert not rbac.superadmin_hidden_block_applies(
        superadmin, makerspace.id, rbac.Action.MANAGE_EVENTS
    )
    assert rbac.superadmin_hidden_block_applies(
        superadmin, makerspace.id, rbac.Action.EDIT_INVENTORY
    )


def test_archived_makerspaces_deny_members_and_superadmins_and_leave_all_scopes():
    makerspace = make_makerspace("dual-read-archived")
    user = make_user("archived-member")
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=seeded_role(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
    )
    superadmin = make_user(
        "archived-superadmin",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
        is_staff=True,
    )
    makerspace.archived_at = timezone.now()
    makerspace.save(update_fields=["archived_at"])

    assert not rbac.can(user, rbac.Action.VIEW_INVENTORY, makerspace.id)
    assert not rbac.can(superadmin, rbac.Action.VIEW_INVENTORY, makerspace.id)
    assert rbac.resolve_scope(user) == set()
    assert rbac.makerspaces_for_action(user, rbac.Action.VIEW_INVENTORY) == set()
    assert rbac.makerspaces_for_action(superadmin, rbac.Action.VIEW_INVENTORY) == set()
    assert not rbac.scope_by_makerspace(user, Makerspace.objects.all()).exists()
    assert not rbac.scope_by_action(
        superadmin, rbac.Action.VIEW_INVENTORY, Makerspace.objects.all()
    ).exists()


def test_visible_global_superadmin_preserves_all_fast_paths():
    make_makerspace("dual-read-visible")
    superadmin = make_user(
        "visible-superadmin",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
        is_staff=True,
    )

    assert rbac.resolve_scope(superadmin) is rbac.ALL
    assert rbac.makerspaces_for_action(superadmin, rbac.Action.VIEW_INVENTORY) is rbac.ALL


def test_string_makerspace_ids_match_integer_ids_and_membership_role_stays_display_only():
    makerspace = make_makerspace("dual-read-string-id")
    user = make_user("string-id-user")
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.PRINT_MANAGER,
        assigned_role=seeded_role(makerspace, MakerspaceMembership.Role.PRINT_MANAGER),
    )

    assert rbac.can(user, rbac.Action.MANAGE_PRINTING, str(makerspace.id)) == rbac.can(
        user, rbac.Action.MANAGE_PRINTING, makerspace.id
    )
    # Compatibility/display only: authority above is resolved from assigned-role actions.
    assert rbac.membership_role(user, makerspace.id) == MakerspaceMembership.Role.PRINT_MANAGER
