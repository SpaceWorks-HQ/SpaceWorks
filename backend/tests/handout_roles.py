"""Build a front-desk (handover-only) staffer the way a makerspace now has to.

Guest Admin was a built-in role until migrations `0052`/`0053` retired it: the seeded row
became an ordinary custom role, the memberships moved onto real role rows, and both enum
members went. Handover is a local arrangement now -- a custom role holding the handout
actions, named whatever the space calls that job -- so tests construct one the same way an
operator would rather than naming a role that no longer exists.

The default action set is deliberately the exact six the retired built-in granted, so every
test that asserted a guest admin's boundaries still asserts the same boundary.
``COLLECT_SERVICE_REQUEST`` is NOT among them even though `rbac.HANDOUT_ACTIONS` includes
it: that set describes what still *reads* as front-desk work, and the built-in never
granted collection. Pass ``actions=`` for a role that should also hand over machine jobs.
"""

from django.contrib.auth import get_user_model

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole

FRONT_DESK_ACTIONS = (
    rbac.Action.VIEW_INVENTORY,
    rbac.Action.ASSIGN_BOX,
    rbac.Action.ISSUE_REQUEST,
    rbac.Action.ISSUE_DIRECT_LOAN,
    rbac.Action.RETURN_REQUEST,
    rbac.Action.UPLOAD_EVIDENCE,
)


def handout_role(makerspace, *, slug="front-desk", actions=FRONT_DESK_ACTIONS):
    """Get or create this makerspace's handover role."""
    role, _ = MakerspaceRole.objects.get_or_create(
        makerspace=makerspace,
        slug=slug,
        defaults={
            "name": slug.replace("-", " ").replace("_", " ").title(),
            "granted_actions": sorted(actions),
        },
    )
    return role


def grant_handout(user, makerspace, **kwargs):
    """Attach an existing user to this makerspace as front-desk staff."""
    return MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=handout_role(makerspace, **kwargs),
    )


def make_handout_member(username, makerspace, **kwargs):
    """Create an active user holding only this makerspace's handover role."""
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    grant_handout(user, makerspace, **kwargs)
    return user
