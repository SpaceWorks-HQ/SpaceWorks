"""Membership identity and outcome helpers shared by admission and legacy paths."""
from rest_framework.exceptions import ValidationError
from apps.makerspaces.models import MakerspaceRole


class MembershipOutcome(dict):
    """DTO that preserves the old ``id``/``state`` read surface until J2 rewires it."""

    @property
    def id(self):
        return self.get("request_id") or self.get("membership_id")

    @property
    def pk(self):
        return self.id

    @property
    def state(self):
        return self.get("state")


def normalized_email(value):
    return (value or "").strip().lower()


def _eligible_user(user):
    return bool(user and user.is_active and user.email_verified_at and user.email)


def _approvable_user(user):
    return bool(user and user.is_active and user.email)


def _is_community_invitation(role):
    """Whether an invitation is for plain community membership rather than staff.

    `invite_membership` issues both down one path, discriminated by the assigned role:
    the protected Member role (and any custom role granting no actions) confers no
    staff authority, so it is a community invitation and belongs to the `membership`
    module. A role granting actions is a staff invitation, which must keep working
    with `membership` off -- MakerspaceMembership is core RBAC state, and locking
    staff administration behind an optional module would strand the makerspace.
    """
    return not role.granted_actions


def _member_role(makerspace):
    try:
        return MakerspaceRole.objects.get(
            makerspace=makerspace, slug="member", is_default=True, is_protected=True
        )
    except MakerspaceRole.DoesNotExist as exc:
        raise ValidationError({"detail": "This makerspace has no protected Member role."}) from exc


def _outcome(*, outcome, membership=None, request=None):
    result = MembershipOutcome(outcome=outcome)
    if membership is not None:
        result["membership_id"] = membership.pk
    if request is not None:
        result["request_id"] = request.pk
    result["state"] = membership.status if membership is not None else request.state
    return result


