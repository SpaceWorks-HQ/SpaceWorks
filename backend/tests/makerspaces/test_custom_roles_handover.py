"""Retired handover roles preserve authority without recreating built-in defaults."""
import pytest

from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.makerspaces.test_custom_roles_l1 import make_user


@pytest.mark.django_db(transaction=True)
def test_a_new_makerspace_gets_no_guest_admin_role():
    """Handover is a local arrangement, not something every space is issued."""
    makerspace = Makerspace.objects.create(name="No guest", slug="no-guest")

    assert not MakerspaceRole.objects.filter(
        makerspace=makerspace, legacy_role="guest_admin"
    ).exists()
    assert not MakerspaceRole.objects.filter(makerspace=makerspace, slug="guest_admin").exists()


@pytest.mark.django_db(transaction=True)
def test_the_migration_converts_a_seeded_guest_admin_without_touching_its_actions():
    """Converting in place is the point: memberships PROTECT the row, so it cannot be
    dropped and recreated without revoking everyone who holds it."""
    from importlib import import_module

    makerspace = Makerspace.objects.create(name="Legacy guest", slug="legacy-guest")
    legacy = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name="Guest Admin",
        slug="guest_admin",
        legacy_role="guest_admin",
        granted_actions=["assign_box", "issue_request", "return_request", "view_inventory"],
        is_default=True,
        is_protected=True,
    )
    holder = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=make_user("legacy-guest-holder"), assigned_role=legacy,
    )

    module = import_module("apps.makerspaces.migrations.0052_retire_builtin_guest_admin_role")
    module.forwards(_LiveApps(), None)

    legacy.refresh_from_db()
    assert legacy.legacy_role is None
    assert legacy.is_default is False
    assert legacy.is_protected is False
    # Untouched: identity, authority and the assignment.
    assert legacy.name == "Guest Admin"
    assert legacy.granted_actions == [
        "assign_box", "issue_request", "return_request", "view_inventory"
    ]
    holder.refresh_from_db()
    assert holder.assigned_role_id == legacy.pk


@pytest.mark.django_db(transaction=True)
def test_0053_moves_a_null_fk_guest_membership_onto_a_role_with_the_same_authority():
    """The null-FK membership is the one that was living off the frozen fallback, so it is
    the one that loses authority if the conversion gets the action set wrong."""
    from importlib import import_module

    makerspace = Makerspace.objects.create(name="Null fk guest", slug="null-fk-guest")
    stale = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=make_user("null-fk-guest-holder"),
        role="guest_admin",
        assigned_role=None,
    )

    module = import_module("apps.makerspaces.migrations.0053_convert_guest_admin_memberships")
    module.forwards(_LiveApps(), None)

    stale.refresh_from_db()
    assert stale.role == MakerspaceMembership.Role.CUSTOM
    assert stale.assigned_role is not None
    # Exactly the six the retired built-in granted -- widening here would be a silent grant.
    assert stale.assigned_role.granted_actions == [
        "assign_box", "issue_direct_loan", "issue_request",
        "return_request", "upload_evidence", "view_inventory",
    ]
    assert stale.assigned_role.legacy_role is None
    assert stale.assigned_role.is_default is False


@pytest.mark.django_db(transaction=True)
def test_0053_reuses_an_untouched_handover_role_rather_than_making_a_second_one():
    from importlib import import_module

    makerspace = Makerspace.objects.create(name="Reuse guest", slug="reuse-guest")
    converted = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name="Guest Admin",
        slug="guest_admin",
        legacy_role=None,
        granted_actions=[
            "assign_box", "issue_direct_loan", "issue_request",
            "return_request", "upload_evidence", "view_inventory",
        ],
        is_default=False,
        is_protected=False,
    )
    stale = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=make_user("reuse-guest-holder"),
        role="guest_admin",
        assigned_role=None,
    )

    module = import_module("apps.makerspaces.migrations.0053_convert_guest_admin_memberships")
    module.forwards(_LiveApps(), None)

    stale.refresh_from_db()
    assert stale.assigned_role_id == converted.pk
    assert not MakerspaceRole.objects.filter(
        makerspace=makerspace, slug__startswith="front-desk"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_0053_does_not_widen_a_membership_whose_handover_role_was_reshaped():
    """An operator who widened the converted role after 0052 must not have that widening
    handed to a membership that was still resolving through the frozen six."""
    from importlib import import_module

    makerspace = Makerspace.objects.create(name="Widened guest", slug="widened-guest")
    widened = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name="Guest Admin",
        slug="guest_admin",
        legacy_role=None,
        granted_actions=["edit_inventory", "issue_request", "view_inventory"],
        is_default=False,
        is_protected=False,
    )
    stale = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=make_user("widened-guest-holder"),
        role="guest_admin",
        assigned_role=None,
    )

    module = import_module("apps.makerspaces.migrations.0053_convert_guest_admin_memberships")
    module.forwards(_LiveApps(), None)

    stale.refresh_from_db()
    assert stale.assigned_role_id != widened.pk
    assert stale.assigned_role.slug == "front-desk"
    assert "edit_inventory" not in stale.assigned_role.granted_actions


class _LiveApps:
    """Stand-in for the migration `apps` registry, using the real models.

    The converted columns are plain fields with no historical divergence, so the live
    model answers identically and this avoids replaying the whole graph for one UPDATE.
    """

    @staticmethod
    def get_model(app_label, model_name):
        from django.apps import apps as django_apps

        return django_apps.get_model(app_label, model_name)


@pytest.mark.django_db(transaction=True)
def test_a_converted_handover_role_can_be_freely_edited_and_deleted():
    """The cap is gone with the built-in: it keyed on `legacy_role`, now null."""
    from apps.accounts import rbac
    from apps.makerspaces import role_services

    makerspace = Makerspace.objects.create(name="Free guest", slug="free-guest")
    actor = make_user("free-guest-manager")
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=actor,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="space_manager"),
    )
    converted = MakerspaceRole.objects.create(
        makerspace=makerspace, name="Front Desk", slug="front-desk",
        granted_actions=["issue_request", "view_inventory"],
    )

    # Widened past the old handout ceiling, which a protected Guest Admin refused.
    role_services.update_role(
        makerspace=makerspace, role=converted, actor=actor,
        granted_actions=["edit_inventory", "issue_request", "view_inventory"],
    )
    converted.refresh_from_db()
    assert rbac.Action.EDIT_INVENTORY in converted.granted_actions

    role_services.delete_role(makerspace=makerspace, role=converted, actor=actor)
    assert not MakerspaceRole.objects.filter(pk=converted.pk).exists()
