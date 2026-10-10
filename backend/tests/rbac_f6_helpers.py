"""Actors and tenant-local records for the finer RBAC endpoint matrix."""
from django.utils import timezone

from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.payments.models import Payment
from tests.return_helpers import make_user


def custom_actor(space, actions, name="delegate"):
    user = make_user(f"{space.slug}-{name}", access_status="active")
    role = MakerspaceRole.objects.create(
        makerspace=space, name=name, slug=name, granted_actions=list(actions),
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=user, assigned_role=role, role="custom",
    )
    return user


def community_member(space, name="member"):
    user = make_user(f"{space.slug}-{name}", access_status="active")
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return MakerspaceMembership.objects.create(
        makerspace=space, user=user,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        role="custom",
    )


def charge(space, membership, status="pending"):
    return Payment.objects.create(
        makerspace=space, member=membership.user, created_by=membership.user,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk, amount="12.00", currency="usd", status=status,
    )
