import pytest
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.services_user_access import reset_user_password
from apps.integrations.models import EmailNotificationMute
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


pytestmark = pytest.mark.django_db


def make_user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="password",
        access_status=User.AccessStatus.ACTIVE,
    )


def make_makerspace(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def seeded_role(makerspace, legacy_role):
    return MakerspaceRole.objects.get(
        makerspace=makerspace,
        legacy_role=legacy_role,
    )


def custom_role(makerspace, slug, actions):
    return MakerspaceRole.objects.create(
        makerspace=makerspace,
        name=slug.replace("-", " ").title(),
        slug=slug,
        granted_actions=sorted(actions),
    )


def membership(user, makerspace, role, assigned_role):
    return MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=role,
        assigned_role=assigned_role,
    )


def test_space_manager_reset_guard_uses_effective_manage_makerspace_action():
    makerspace = make_makerspace("l2b-reset")
    actor = make_user("l2b-reset-actor")
    membership(
        actor,
        makerspace,
        MakerspaceMembership.Role.SPACE_MANAGER,
        seeded_role(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
    )
    governance_role = custom_role(
        makerspace, "governance", {rbac.Action.MANAGE_MAKERSPACE}
    )
    custom_governance_peer = make_user("l2b-custom-governance-peer")
    membership(
        custom_governance_peer,
        makerspace,
        MakerspaceMembership.Role.CUSTOM,
        governance_role,
    )

    with pytest.raises(PermissionDenied, match="Cannot reset another Space Manager"):
        reset_user_password(actor, custom_governance_peer.pk)

    inventory_peer = make_user("l2b-inventory-peer")
    membership(
        inventory_peer,
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
        seeded_role(makerspace, MakerspaceMembership.Role.INVENTORY_MANAGER),
    )
    assert reset_user_password(actor, inventory_peer.pk).user == inventory_peer

    default_governance_peer = make_user("l2b-default-governance-peer")
    membership(
        default_governance_peer,
        makerspace,
        MakerspaceMembership.Role.SPACE_MANAGER,
        seeded_role(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
    )
    with pytest.raises(PermissionDenied, match="Cannot reset another Space Manager"):
        reset_user_password(actor, default_governance_peer.pk)


def test_printing_recipients_follow_actions_but_mute_display_roles():
    makerspace = make_makerspace("l2b-printing-recipients")
    allowed_custom = make_user("l2b-printing-custom-allowed")
    membership(
        allowed_custom,
        makerspace,
        MakerspaceMembership.Role.CUSTOM,
        custom_role(makerspace, "print-custom", {rbac.Action.MANAGE_PRINTING}),
    )
    denied_custom = make_user("l2b-printing-custom-denied")
    membership(
        denied_custom,
        makerspace,
        MakerspaceMembership.Role.CUSTOM,
        custom_role(makerspace, "non-print-custom", {rbac.Action.MANAGE_EVENTS}),
    )
    space_manager = make_user("l2b-printing-space-manager")
    membership(
        space_manager,
        makerspace,
        MakerspaceMembership.Role.SPACE_MANAGER,
        seeded_role(makerspace, MakerspaceMembership.Role.SPACE_MANAGER),
    )
    print_manager = make_user("l2b-printing-print-manager")
    membership(
        print_manager,
        makerspace,
        MakerspaceMembership.Role.PRINT_MANAGER,
        custom_role(makerspace, "legacy-print-manager", {rbac.Action.MANAGE_PRINTING}),
    )
    inventory_manager = make_user("l2b-printing-inventory-manager")
    membership(
        inventory_manager,
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
        seeded_role(makerspace, MakerspaceMembership.Role.INVENTORY_MANAGER),
    )
    EmailNotificationMute.objects.create(
        makerspace=makerspace,
        target=MakerspaceMembership.Role.SPACE_MANAGER,
        stream="printing",
        event="accepted",
        audience="staff",
    )

    emails = staff_emails_for_feature(makerspace, "printing", event="accepted")

    assert allowed_custom.email in emails
    assert denied_custom.email not in emails
    assert space_manager.email not in emails
    assert print_manager.email in emails
    assert inventory_manager.email not in emails


def test_handout_only_recognises_custom_handout_roles():
    makerspace = make_makerspace("l2b-handout-only")
    custom_handout = make_user("l2b-custom-handout")
    membership(
        custom_handout,
        makerspace,
        MakerspaceMembership.Role.CUSTOM,
        custom_role(makerspace, "handout-custom", rbac.HANDOUT_ACTIONS),
    )
    broader_custom = make_user("l2b-broader-custom")
    membership(
        broader_custom,
        makerspace,
        MakerspaceMembership.Role.CUSTOM,
        custom_role(
            makerspace,
            "broader-custom",
            rbac.HANDOUT_ACTIONS | {rbac.Action.EDIT_INVENTORY},
        ),
    )

    assert rbac.is_handout_only(custom_handout, makerspace.id)
    assert not rbac.is_handout_only(broader_custom, makerspace.id)


def test_a_retired_guest_admin_membership_string_now_grants_nothing():
    """The removal must stay removed, and must fail CLOSED when it does not.

    Migration 0053 moved every such membership onto a real role row, so no row should hold
    this string at all. If one somehow does -- a hand-written INSERT, a restored old dump --
    the frozen `_MEMBERSHIP_ROLE_ACTIONS` entry is gone, so it resolves to no actions rather
    than to the six the retired built-in used to carry. This is the one place the retired
    string is still named on purpose: naming it is what pins the fail-closed behaviour.
    """
    makerspace = make_makerspace("l2b-retired-guest")
    stale = make_user("l2b-retired-guest-user")
    membership(stale, makerspace, "guest_admin", None)

    assert rbac.effective_actions(stale, makerspace.id) == set()
    assert not rbac.is_handout_only(stale, makerspace.id)
    assert rbac.can(stale, rbac.Action.ISSUE_REQUEST, makerspace.id) is False


def test_switcher_includes_custom_event_only_membership():
    makerspace = make_makerspace("l2b-events-switcher")
    user = make_user("l2b-events-switcher-user")
    membership(
        user,
        makerspace,
        MakerspaceMembership.Role.CUSTOM,
        custom_role(makerspace, "events-only", {rbac.Action.MANAGE_EVENTS}),
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(reverse("admin-makerspaces"))

    assert response.status_code == 200
    assert makerspace.id in {row["id"] for row in response.data}
