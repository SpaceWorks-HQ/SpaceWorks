import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts import rbac
from apps.accounts.models import User
from apps.accounts.serializers import user_payload
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def seeded(makerspace, legacy_role):
    return MakerspaceRole.objects.get(makerspace=makerspace, legacy_role=legacy_role)


def active_staff(username):
    return make_user(
        username,
        role=User.Role.SPACE_MANAGER,
        password="pw-strong-123",
        access_status=User.AccessStatus.ACTIVE,
    )


def membership_payload(user, makerspace):
    return next(
        item for item in user_payload(user)["makerspaces"] if item["id"] == makerspace.id
    )


def test_seeded_default_role_includes_metadata_and_effective_actions():
    makerspace = make_space("auth-payload-default")
    user = active_staff("auth-payload-default-user")
    membership = MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        assigned_role=seeded(makerspace, MakerspaceMembership.Role.INVENTORY_MANAGER),
    )

    payload = membership_payload(user, makerspace)

    assert payload == {
        "id": makerspace.id,
        "slug": makerspace.slug,
        "role": membership.role,
        "role_id": membership.assigned_role_id,
        "role_name": membership.assigned_role.name,
        "role_slug": membership.assigned_role.slug,
        "actions": sorted(rbac.effective_actions(user, makerspace.id)),
        "can_configure_machine_types": False,
        "can_refer": True,
        "can_verify": False,
        "verified_at": None,
        "referrals_enabled": False,
    }
    assert payload["actions"] == sorted(membership.assigned_role.granted_actions)


def test_custom_role_includes_its_assigned_actions():
    makerspace = make_space("auth-payload-custom")
    user = active_staff("auth-payload-custom-user")
    role = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name="Loan Desk",
        slug="loan-desk",
        granted_actions=[rbac.Action.VIEW_INVENTORY, rbac.Action.ISSUE_REQUEST],
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )

    payload = membership_payload(user, makerspace)

    assert payload["role"] == MakerspaceMembership.Role.CUSTOM
    assert payload["role_id"] == role.id
    assert payload["role_name"] == role.name
    assert payload["role_slug"] == role.slug
    assert payload["actions"] == sorted(role.granted_actions)


def test_null_assigned_role_uses_legacy_metadata_and_actions():
    makerspace = make_space("auth-payload-fallback")
    user = active_staff("auth-payload-fallback-user")
    # PRINT_MANAGER, because it is the legacy string still carried by
    # `rbac._MEMBERSHIP_ROLE_ACTIONS` as the frozen null-FK fallback. `guest_admin` used to
    # serve here and no longer can: migration 0053 emptied it and the enum member is gone.
    role = MakerspaceMembership.Role.PRINT_MANAGER
    MakerspaceMembership.objects.create(user=user, makerspace=makerspace, role=role)

    payload = membership_payload(user, makerspace)

    assert payload["role_id"] is None
    assert payload["role_slug"] == role
    assert payload["role_name"] == MakerspaceMembership.Role(role).label
    assert payload["actions"] == sorted(rbac.effective_actions(user, makerspace.id))


def test_login_and_me_return_identical_membership_shapes():
    makerspace = make_space("auth-payload-parity")
    user = active_staff("auth-payload-parity-user")
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=seeded(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
    )

    login = APIClient().post(
        LOGIN,
        {"username": user.username, "password": "pw-strong-123"},
        format="json",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    me = client.get(ME)

    assert login.status_code == 200
    assert me.status_code == 200
    assert login.data["user"]["makerspaces"] == me.data["makerspaces"]


def test_archived_makerspace_membership_is_excluded():
    visible = make_space("auth-payload-visible")
    archived = make_space("auth-payload-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    user = active_staff("auth-payload-archived-user")
    for makerspace in (visible, archived):
        MakerspaceMembership.objects.create(
            user=user,
            makerspace=makerspace,
            role=MakerspaceMembership.Role.SPACE_MANAGER,
            assigned_role=seeded(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
        )

    assert {row["id"] for row in user_payload(user)["makerspaces"]} == {visible.id}


def test_hidden_makerspace_superadmin_requires_membership_and_is_membership_limited():
    hidden = make_space("auth-payload-hidden")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user(
        "auth-payload-hidden-root",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )

    assert hidden.id not in {row["id"] for row in user_payload(superadmin)["makerspaces"]}

    role = MakerspaceRole.objects.create(
        makerspace=hidden,
        name="Hidden Reader",
        slug="hidden-reader",
        granted_actions=[rbac.Action.VIEW_INVENTORY],
    )
    MakerspaceMembership.objects.create(
        user=superadmin,
        makerspace=hidden,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )

    payload = membership_payload(superadmin, hidden)

    assert payload["actions"] == sorted(role.granted_actions)
    assert payload["actions"] != sorted(rbac.ROLE_GRANTABLE_ACTIONS)


def test_branded_origin_scopes_memberships_and_actions_exclude_superadmin_only_values():
    makerspace_a = make_space("auth-payload-origin-a")
    makerspace_a.frontend_domain = "auth-payload-a.example"
    makerspace_a.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    makerspace_a.save(update_fields=["frontend_domain", "frontend_domain_status"])
    makerspace_b = make_space("auth-payload-origin-b")
    user = active_staff("auth-payload-origin-user")
    for makerspace in (makerspace_a, makerspace_b):
        MakerspaceMembership.objects.create(
            user=user,
            makerspace=makerspace,
            role=MakerspaceMembership.Role.SPACE_MANAGER,
            assigned_role=seeded(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
        )

    request = APIRequestFactory().get(ME, HTTP_ORIGIN="https://auth-payload-a.example")
    payload = user_payload(user, request=request)

    assert [row["id"] for row in payload["makerspaces"]] == [makerspace_a.id]
    for membership in payload["makerspaces"]:
        assert rbac.Action.TRANSFER_STOCK not in membership["actions"]
        assert rbac.Action.MANAGE_STAFF not in membership["actions"]


def _payload_query_count(user):
    with CaptureQueriesContext(connection) as ctx:
        user_payload(user)
    return len(ctx)


def test_auth_payload_query_count_does_not_scale_with_memberships():
    # Regression guard: actions are derived from the already select_related-loaded rows, so
    # /auth/me + /auth/login stay O(1) queries instead of the old 1+2N (one effective_actions
    # call per membership).
    one_user = active_staff("auth-payload-q1")
    one_space = make_space("auth-payload-q1-space")
    MakerspaceMembership.objects.create(
        user=one_user,
        makerspace=one_space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=seeded(one_space, MakerspaceMembership.Role.SPACE_MANAGER),
    )
    many_user = active_staff("auth-payload-q4")
    for i in range(4):
        space = make_space(f"auth-payload-q4-space-{i}")
        MakerspaceMembership.objects.create(
            user=many_user,
            makerspace=space,
            role=MakerspaceMembership.Role.SPACE_MANAGER,
            assigned_role=seeded(space, MakerspaceMembership.Role.SPACE_MANAGER),
        )

    assert len(user_payload(many_user)["makerspaces"]) == 4
    # Same query count for 1 vs 4 memberships => no per-membership query.
    assert _payload_query_count(many_user) == _payload_query_count(one_user)
