"""Staff-created person records for people who will never hold an account.

This is the identity path an accounts-off deployment runs on, and it is deliberately
**not** gated by any module. A person record is core RBAC state, the same reasoning
that keeps the staff roster ungated (plan A7), while `accounts` now means self-service
enrolment rather than identity itself. This path stays available with `accounts` on
too: a space that runs member accounts still has walk-ins at the counter.

The record is a real `User` with an **unusable password** and no verified email, which
is what makes creating one an act of *naming a person*, not of provisioning a login.
Everything downstream then works untouched, because every requester relation in the
system is a non-null PROTECT FK to `User` on a PII-mapped model: direct handouts,
machine-service jobs submitted on a member's behalf, accountability and the
access-restriction flow all take this row exactly as they take a self-registered one.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.username_allocation import allocate_username
from apps.audit import services as audit
from apps.makerspaces.membership_activation import _activate_membership
from apps.makerspaces.membership_services import _member_role, normalized_email
from apps.makerspaces.models import Makerspace

def create_walk_in_member(actor, makerspace, *, display_name, email="", phone=""):
    """Create a person record and activate it as a plain member of `makerspace`."""
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValidationError({"display_name": "A name is required."})
    email = normalized_email(email)
    phone = (phone or "").strip()

    with transaction.atomic():
        # Makerspace first, matching the lock order every membership service uses. A
        # concurrent role edit and walk-in creation otherwise take the two rows in
        # opposite orders and deadlock.
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        user = _new_user(display_name, email, phone)
        membership = _activate_membership(
            actor, makerspace, user, _member_role(makerspace), source="walk_in"
        )
        # Referral invitations auto-activate. A staff-created bearer identity must not
        # inherit that delegation from the model's historical default.
        if membership.can_refer:
            membership.can_refer = False
            membership.save(update_fields=["can_refer"])
        audit.record(
            actor,
            "member.walk_in_created",
            makerspace=makerspace,
            target=membership,
            meta={"has_email": bool(email), "has_phone": bool(phone)},
        )
        return membership


def _new_user(display_name, email, phone):
    """A fresh person record. This path NEVER binds to an existing account.

    A typed email that already belongs to someone is refused rather than attached, and
    that refusal is the security boundary of this endpoint. Binding an account to a
    roster is a membership decision -- it belongs to the members list under
    `MANAGE_MAKERSPACE`, not to a front-desk form held by anyone with
    `ISSUE_DIRECT_LOAN`. Attaching instead would also silently reactivate a membership
    someone deliberately revoked, through the one form whose entire purpose is naming a
    stranger.
    """
    if email and User.objects.filter(email__iexact=email).exists():
        raise ValidationError(
            {"email": "An account already uses that email. Add them from the members list."}
        )

    def create(username):
        user = User(
            username=username,
            display_name=display_name[:200],
            email=email,
            # Free-text contact only. NEVER `phone_e164`: that column is a login
            # identity, and counter-entered contact has not been verified.
            phone=phone[:32],
            role=User.Role.REQUESTER,
            access_status=User.AccessStatus.ACTIVE,
            # This marker, not merely an unusable password, blocks recovery paths.
            is_walk_in=True,
        )
        user.set_unusable_password()
        user.save()
        return user

    return allocate_username(display_name, create=create)
