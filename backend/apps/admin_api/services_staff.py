"""Shared, transactional staff membership attachment helpers."""

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils.crypto import get_random_string
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


_SM_DELEGABLE_ROLES = (
    MakerspaceMembership.Role.PRINT_MANAGER,
    MakerspaceMembership.Role.INVENTORY_MANAGER,
    MakerspaceMembership.Role.MACHINE_MANAGER,
)


def _global_role_for_membership(legacy_role):
    # The GUEST_ADMIN branch is gone with the built-in role. `User.Role.GUEST_ADMIN` stays
    # in the enum because existing user rows hold that value, but nothing assigns it any
    # more -- and it gated nothing reachable: its only consumer is `STAFF_ROLES`, read by
    # `IsStaff`, whose sole `StaffAPIView` subclass overrides `permission_classes`.
    if legacy_role == MakerspaceMembership.Role.SPACE_MANAGER:
        return User.Role.SPACE_MANAGER
    return User.Role.REQUESTER


def attach_staff_membership(
    *, actor, makerspace, username, email="", first_name="", last_name="", password="", role
):
    """Create or attach a user to a role, rolling all writes back on failure."""
    actor_is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
    is_break_glass = (
        actor_is_superadmin
        and not makerspace.superadmin_access_enabled
        and role.legacy_role == MakerspaceMembership.Role.SPACE_MANAGER
    )
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        role = MakerspaceRole.objects.select_for_update().get(
            pk=role.pk, makerspace=makerspace
        )
        legacy_role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
        user_defaults = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "role": _global_role_for_membership(role.legacy_role),
            "password": make_password(password or get_random_string(32)),
        }
        if is_break_glass:
            errors = {}
            if User.objects.filter(username=username).exists():
                errors["username"] = "A user with that username already exists."
            if email and User.objects.filter(email__iexact=email).exists():
                errors["email"] = "A user with that email already exists."
            if errors:
                raise ValidationError(errors)
            user = User.objects.create(username=username, **user_defaults)
            limits.check_quota(makerspace, "staff", adding=1)
            membership = MakerspaceMembership.objects.create(
                user=user,
                makerspace=makerspace,
                role=legacy_role,
                assigned_role=role,
            )
            created = True
        else:
            user, created = User.objects.get_or_create(
                username=username, defaults=user_defaults
            )
            if not actor_is_superadmin:
                existing_role = (
                    MakerspaceMembership.objects.select_for_update()
                    .filter(makerspace=makerspace, user=user)
                    .values_list("role", flat=True)
                    .first()
                )
                if existing_role is not None and existing_role not in _SM_DELEGABLE_ROLES:
                    raise PermissionDenied(
                        "Only a superadmin can change a Space Manager membership."
                    )
            has_active_membership = MakerspaceMembership.objects.filter(
                user=user,
                makerspace=makerspace,
                status="active",
                user__is_active=True,
                user__access_status=User.AccessStatus.ACTIVE,
            ).exists()
            if not has_active_membership and user.is_active and (
                user.access_status == User.AccessStatus.ACTIVE
            ):
                limits.check_quota(makerspace, "staff", adding=1)
            # Only NEW accounts take a global User.role from the membership (via
            # get_or_create defaults above). Never rewrite an EXISTING account's global
            # role here: doing so would let a manager add a known non-is_superuser global
            # superadmin as a delegable/custom role and silently strip their global
            # authority (P1). Authority is per-makerspace via the membership anyway.
            # Re-adding a previously revoked staff member must reactivate the row, not
            # leave status="revoked" (which the M2 RBAC paths treat as no access).
            membership, _ = MakerspaceMembership.objects.update_or_create(
                user=user,
                makerspace=makerspace,
                defaults={
                    "role": legacy_role,
                    "assigned_role": role,
                    "status": "active",
                    "revoked_at": None,
                    "revoked_by": None,
                    "revocation_reason": "",
                },
            )
        return membership, created, is_break_glass
