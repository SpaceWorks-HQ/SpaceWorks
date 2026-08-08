"""Per-event recipient selection (Notifications v2, N1).

The load-bearing assertion in this file is `test_no_rows_keeps_todays_behaviour_*`: the
absence of a selection must resolve to the action-based default, NOT to nobody. Bookings
email is ON by default in `DEFAULT_CHANNEL_STATE`, so a "default nobody" reading would
have silently stopped booking mail that flows in production today.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import User
from apps.integrations import recipients
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)
from apps.integrations.staff_notifications import (
    staff_emails_for_feature,
    staff_user_ids_for_feature,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles

pytestmark = pytest.mark.django_db


def make_space(slug):
    space = Makerspace.objects.create(name=slug, slug=slug)
    ensure_default_roles(space)
    return space


def role_of(space, slug):
    return MakerspaceRole.objects.get(makerspace=space, slug=slug)


def make_member(username, space, *, role_slug="member", legacy=MakerspaceMembership.Role.CUSTOM, **kw):
    user = get_user_model().objects.create_user(
        username=username,
        email=kw.pop("email", f"{username}@e.com"),
        role=kw.pop("user_role", User.Role.REQUESTER),
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=legacy,
        assigned_role=role_of(space, role_slug) if role_slug else None,
        **kw,
    )
    return user


def select(space, feature, event, kind, *, role=None, user=None):
    return NotificationRecipient.objects.create(
        makerspace=space, feature=feature, event=event, kind=kind, role=role, user=user
    )


# --- D3: no rows means today's behaviour -------------------------------------------


def test_no_rows_keeps_todays_behaviour_for_bookings():
    """The regression this whole semantic exists to prevent."""
    space = make_space("recip-bookings-default")
    manager = make_member(
        "recip-bookings-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    make_member("recip-bookings-plain", space)

    assert staff_emails_for_feature(space, "bookings", event="created") == [manager.email]


def test_no_rows_keeps_todays_behaviour_for_maintenance():
    space = make_space("recip-maint-default")
    machine_manager = make_member(
        "recip-maint-manager",
        space,
        role_slug="machine_manager",
        legacy=MakerspaceMembership.Role.MACHINE_MANAGER,
    )

    assert staff_emails_for_feature(space, "maintenance", event="logged") == [
        machine_manager.email
    ]


def test_a_row_for_another_event_does_not_capture_this_one():
    space = make_space("recip-event-scoped")
    manager = make_member(
        "recip-event-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    member = make_member("recip-event-member", space)
    select(space, "bookings", "cancelled", NotificationRecipientKind.MEMBERS)

    # "created" has no selection -> the action-based default still applies.
    assert staff_emails_for_feature(space, "bookings", event="created") == [manager.email]
    # "cancelled" does -> members win, and the manager is a member so they stay in.
    assert sorted(staff_emails_for_feature(space, "bookings", event="cancelled")) == sorted(
        [manager.email, member.email]
    )


def test_selection_is_ignored_for_mute_based_features():
    """hardware/printing keep EmailNotificationMute untouched — never selection rows."""
    space = make_space("recip-hardware-untouched")
    manager = make_member(
        "recip-hardware-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    make_member("recip-hardware-member", space)
    select(space, "hardware_requests", "submitted", NotificationRecipientKind.MEMBERS)

    assert staff_emails_for_feature(space, "hardware_requests", event="submitted") == [
        manager.email
    ]


# --- D2: the four recipient kinds ---------------------------------------------------


def test_role_selection_replaces_the_action_default():
    space = make_space("recip-role-selection")
    make_member(
        "recip-role-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    machine_manager = make_member(
        "recip-role-machine",
        space,
        role_slug="machine_manager",
        legacy=MakerspaceMembership.Role.MACHINE_MANAGER,
    )
    select(
        space,
        "bookings",
        "created",
        NotificationRecipientKind.ROLE,
        role=role_of(space, "machine_manager"),
    )

    # The space manager holds MANAGE_BOOKINGS and would be the default recipient; the
    # selection is authoritative, so only the picked role is mailed.
    assert staff_emails_for_feature(space, "bookings", event="created") == [
        machine_manager.email
    ]


def test_requester_kind_produces_no_address():
    """`requester` is a flag the caller reads — never an address this layer emits."""
    space = make_space("recip-requester-flag")
    make_member(
        "recip-requester-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    select(space, "events", "published", NotificationRecipientKind.REQUESTER)

    assert recipients.requester_selected(space, "events", "published") is True
    assert staff_emails_for_feature(space, "events", event="published") == []


def test_members_kind_reaches_every_active_member():
    space = make_space("recip-members-kind")
    manager = make_member(
        "recip-members-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    member = make_member("recip-members-plain", space)
    revoked = make_member("recip-members-revoked", space, status="revoked")
    select(space, "maintenance", "logged", NotificationRecipientKind.MEMBERS)

    emails = staff_emails_for_feature(space, "maintenance", event="logged")
    assert sorted(emails) == sorted([manager.email, member.email])
    assert revoked.email not in emails


# --- D4: a named user must hold a membership here -----------------------------------


def test_named_user_without_a_membership_resolves_to_nobody():
    space = make_space("recip-named-outsider")
    outsider = get_user_model().objects.create_user(
        username="recip-outsider",
        email="recip-outsider@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    select(space, "events", "published", NotificationRecipientKind.USER, user=outsider)

    # Re-checked at send time, not only at the picker: a row written by any other route
    # (admin, fixture, a membership revoked after the pick) must still not be mailed.
    assert staff_emails_for_feature(space, "events", event="published") == []


def test_named_user_with_a_membership_is_mailed():
    space = make_space("recip-named-member")
    named = make_member("recip-named-insider", space)
    select(space, "events", "published", NotificationRecipientKind.USER, user=named)

    assert staff_emails_for_feature(space, "events", event="published") == [named.email]


def test_named_user_from_another_makerspace_is_inert():
    space = make_space("recip-named-tenant-a")
    other = make_space("recip-named-tenant-b")
    stranger = make_member("recip-named-stranger", other)
    select(space, "events", "published", NotificationRecipientKind.USER, user=stranger)

    assert staff_emails_for_feature(space, "events", event="published") == []


def test_role_row_pointing_at_another_tenants_role_is_inert():
    space = make_space("recip-role-tenant-a")
    other = make_space("recip-role-tenant-b")
    make_member(
        "recip-role-tenant-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    select(
        space,
        "bookings",
        "created",
        NotificationRecipientKind.ROLE,
        role=role_of(other, "space_manager"),
    )

    # A selection exists, so it is authoritative — and it matches nobody. Failing to an
    # empty list rather than leaking the other tenant's staff is the point.
    assert staff_emails_for_feature(space, "bookings", event="created") == []


# --- D5: the member's own opt-out always wins ---------------------------------------


def test_receives_notifications_opt_out_beats_a_staff_selection():
    space = make_space("recip-opt-out")
    opted_out = make_member("recip-opted-out", space, receives_notifications=False)
    opted_in = make_member("recip-opted-in", space)
    select(space, "maintenance", "logged", NotificationRecipientKind.MEMBERS)

    emails = staff_emails_for_feature(space, "maintenance", event="logged")
    assert emails == [opted_in.email]
    assert opted_out.email not in emails


def test_opt_out_also_wins_when_the_user_is_named_individually():
    space = make_space("recip-opt-out-named")
    named = make_member("recip-opt-out-named-user", space, receives_notifications=False)
    select(space, "events", "published", NotificationRecipientKind.USER, user=named)

    assert staff_emails_for_feature(space, "events", event="published") == []


# --- D8: push follows the same selection --------------------------------------------


def test_push_recipients_follow_the_email_selection():
    space = make_space("recip-push-selection")
    make_member(
        "recip-push-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    member = make_member("recip-push-member", space)
    select(space, "events", "published", NotificationRecipientKind.USER, user=member)

    assert staff_user_ids_for_feature(space, "events", event="published") == [member.pk]


# --- D14: module gating, D15: fail open ---------------------------------------------


def test_stale_rows_for_an_uninstalled_module_fall_back_to_the_default():
    space = make_space("recip-module-gate")
    manager = make_member(
        "recip-module-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    member = make_member("recip-module-member", space)
    select(space, "events", "published", NotificationRecipientKind.USER, user=member)

    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])

    # Falling back rather than muting: D15 says a capability lookup must never be the
    # reason a makerspace stops being alerted.
    assert staff_emails_for_feature(space, "events", event="published") == [manager.email]


def test_a_broken_selection_lookup_falls_back_rather_than_muting(monkeypatch):
    space = make_space("recip-fail-open")
    manager = make_member(
        "recip-fail-open-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )

    def boom(*args, **kwargs):
        raise RuntimeError("selection table unavailable")

    monkeypatch.setattr(recipients.NotificationRecipient.objects, "filter", boom)

    assert staff_emails_for_feature(space, "bookings", event="created") == [manager.email]


def test_module_gate_is_checked_before_the_query(monkeypatch):
    space = make_space("recip-module-first")
    make_member(
        "recip-module-first-manager",
        space,
        role_slug="space_manager",
        legacy=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])

    assert recipients.selection_rows(space, "events", "published") == []
