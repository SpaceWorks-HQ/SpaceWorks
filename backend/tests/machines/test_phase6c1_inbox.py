"""The in-app inbox is withheld from a per-type maintainer (phase 6c1).

A `Notification` carries no machine provenance and its `read_at` is makerspace-wide, so one
team acknowledging a row would silence it for every other team. Rather than hand a scoped
maintainer a feed that cannot be narrowed to them, the inbox is refused outright — an
accepted cost, since email and chat already narrow by machine through recipient rules.

The paired frontend assertion lives in `staffTabs.test.ts`: the tab is omitted rather than
rendered-and-403ing, and the unread badge lives inside that link so it goes with it.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.machines.models import Machine, MachineType, RoleMachineTypeScope
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.notifications.models import Notification
from tests.return_helpers import authenticated_client, make_space, make_user

pytestmark = pytest.mark.django_db


def _urls(space, notification):
    return [
        ("get", reverse("notifications:notifications-list", args=[space.pk])),
        ("get", reverse("notifications:notifications-unread-count", args=[space.pk])),
        ("post", reverse("notifications:notifications-read-all", args=[space.pk])),
        ("post", reverse("notifications:notifications-read", args=[space.pk, notification.pk])),
    ]


def _role_actor(space, username, *, actions, types=()):
    actor = make_user(username, access_status=User.AccessStatus.ACTIVE)
    role = MakerspaceRole.objects.create(
        makerspace=space, name=username, slug=username, granted_actions=list(actions)
    )
    for machine_type in types:
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


@pytest.fixture
def lab():
    space = make_space("phase6c1-inbox")
    lasers = MachineType.objects.create(
        makerspace=space, slug="phase6c1-laser", name="Laser"
    )
    Machine.objects.create(makerspace=space, machine_type=lasers, name="Laser")
    notification = Notification.objects.create(
        makerspace=space, title="Maintenance due", body="Belt"
    )
    return {"space": space, "lasers": lasers, "notification": notification}


def test_every_inbox_endpoint_is_refused_for_a_scoped_maintainer(lab):
    actor = _role_actor(
        lab["space"],
        "phase6c1-maintainer",
        actions=[Action.MANAGE_MACHINES],
        types=[lab["lasers"]],
    )
    client = authenticated_client(actor)

    for method, url in _urls(lab["space"], lab["notification"]):
        response = getattr(client, method)(url)
        assert response.status_code == 403, f"{method.upper()} {url} was not refused"

    # A refused mark-read must not have marked anything.
    lab["notification"].refresh_from_db()
    assert lab["notification"].read_at is None


def test_a_mixed_role_keeps_the_inbox(lab):
    """Machine scoping narrows machine data; it does not revoke inventory authority."""
    actor = _role_actor(
        lab["space"],
        "phase6c1-mixed",
        actions=[Action.MANAGE_MACHINES, Action.VIEW_INVENTORY],
        types=[lab["lasers"]],
    )
    client = authenticated_client(actor)

    for method, url in _urls(lab["space"], lab["notification"]):
        response = getattr(client, method)(url)
        assert response.status_code == 200, f"{method.upper()} {url} was refused"


def test_a_role_storing_manage_printing_keeps_the_inbox(lab):
    """A stored printing grant already authorized the inbox, so it survives.

    `MANAGE_MACHINES` implies `MANAGE_PRINTING`, which is how a pure maintainer reaches this
    gate at all — so the predicate has to read the STORED grant. Asking `rbac.can` would
    make every maintainer look like a print manager and the denial would never fire.
    """
    stored = _role_actor(
        lab["space"],
        "phase6c1-stored-printing",
        actions=[Action.MANAGE_MACHINES, Action.MANAGE_PRINTING],
        types=[lab["lasers"]],
    )
    implied = _role_actor(
        lab["space"],
        "phase6c1-implied-printing",
        actions=[Action.MANAGE_MACHINES],
        types=[lab["lasers"]],
    )
    url = reverse("notifications:notifications-unread-count", args=[lab["space"].pk])

    assert authenticated_client(stored).get(url).status_code == 200
    assert authenticated_client(implied).get(url).status_code == 403

    # The console flag must agree, or the tab and the API disagree.
    def flag(actor):
        response = authenticated_client(actor).get("/api/v1/auth/me")
        row = next(
            m for m in response.data["makerspaces"] if m["id"] == lab["space"].pk
        )
        return row["is_machine_only"]

    assert flag(stored) is False
    assert flag(implied) is True


def test_exempt_actors_keep_the_inbox(lab):
    space = lab["space"]
    space_manager = make_user(
        "phase6c1-sm", access_status=User.AccessStatus.ACTIVE
    )
    MakerspaceMembership.objects.create(
        user=space_manager,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(
            makerspace=space, slug="space_manager"
        ),
    )
    legacy = make_user("phase6c1-legacy", access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=legacy,
        makerspace=space,
        role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=None,
    )
    superadmin = make_user(
        "phase6c1-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )

    for actor in (space_manager, legacy, superadmin):
        response = authenticated_client(actor).get(
            reverse("notifications:notifications-unread-count", args=[space.pk])
        )
        assert response.status_code == 200, f"{actor.username} was refused"


def test_auth_me_reports_is_machine_only_so_the_console_need_not_guess(lab):
    """The console must read this, not derive it — see `getStaffAccess`."""
    maintainer = _role_actor(
        lab["space"],
        "phase6c1-flag-maintainer",
        actions=[Action.MANAGE_MACHINES],
        types=[lab["lasers"]],
    )
    mixed = _role_actor(
        lab["space"],
        "phase6c1-flag-mixed",
        actions=[Action.MANAGE_MACHINES, Action.VIEW_INVENTORY],
        types=[lab["lasers"]],
    )
    legacy = make_user("phase6c1-flag-legacy", access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=legacy,
        makerspace=lab["space"],
        role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=None,
    )

    def flag(actor):
        response = authenticated_client(actor).get("/api/v1/auth/me")
        assert response.status_code == 200
        row = next(
            m for m in response.data["makerspaces"] if m["id"] == lab["space"].pk
        )
        return row["is_machine_only"]

    assert flag(maintainer) is True
    assert flag(mixed) is False
    # A null-`assigned_role` legacy membership is EXEMPT, which is precisely what the
    # console could not have worked out from effective actions.
    assert flag(legacy) is False
