"""Superadmin staff-API routes must respect the tenant envelope.

`rbac.can` excludes hard-hidden and unservable makerspaces for everyone, but a route
whose superadmin branch skips `can` has to restate both halves itself. These pin the
membership-revoke route, which restated only the hidden half.
"""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def superadmin():
    return make_user(
        "envelope-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def staff_membership(space, username):
    make_member(
        username,
        space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    return MakerspaceMembership.objects.get(makerspace=space, user__username=username)


def revoke(actor, membership):
    return authenticated_client(actor).delete(f"/api/v1/admin/memberships/{membership.pk}")


def test_superadmin_revokes_a_membership_of_an_active_space():
    space = make_space("envelope-active")
    membership = staff_membership(space, "envelope-active-staff")

    response = revoke(superadmin(), membership)

    assert response.status_code == 204
    assert not MakerspaceMembership.objects.filter(pk=membership.pk).exists()
    assert AuditLog.objects.filter(action="staff.membership_revoked", makerspace=space).exists()


@pytest.mark.parametrize(
    "state",
    [
        {"archived_at": "now"},
        {"lifecycle_state": Makerspace.LifecycleState.IMPORTING},
        {"lifecycle_state": Makerspace.LifecycleState.ABORTED},
    ],
)
def test_superadmin_cannot_revoke_inside_an_unservable_space(state):
    # Archived is invisible everywhere but /control/, and an importing or aborted tenant
    # is not serving traffic at all; a staff-API delete there is a change nobody can see
    # and, for an archived space, one that unarchiving would silently not undo.
    space = make_space("envelope-unservable")
    membership = staff_membership(space, "envelope-unservable-staff")
    values = {key: (timezone.now() if value == "now" else value) for key, value in state.items()}
    Makerspace.objects.filter(pk=space.pk).update(**values)

    response = revoke(superadmin(), membership)

    assert response.status_code == 404
    assert MakerspaceMembership.objects.filter(pk=membership.pk).exists()
    assert not AuditLog.objects.filter(action="staff.membership_revoked").exists()


def test_space_manager_cannot_revoke_inside_their_own_archived_space():
    space = make_space("envelope-sm-archived")
    manager = make_member("envelope-sm-archived-manager", space)
    membership = staff_membership(space, "envelope-sm-archived-staff")
    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())

    assert revoke(manager, membership).status_code == 404
    assert MakerspaceMembership.objects.filter(pk=membership.pk).exists()
