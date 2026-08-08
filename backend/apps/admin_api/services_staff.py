"""Shared, transactional staff membership attachment helpers."""

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils.crypto import get_random_string
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


def _is_superadmin_only_membership(membership):
    """Whether only a superadmin may re-attach over this existing membership.

    This used to be an allowlist of legacy role *strings*, with SPACE_MANAGER and CUSTOM
    left out of it. That stopped working once the handover built-in was retired: migration
    `0053` moves those memberships to ``custom``, and post-`0052` every newly created
    handover membership already lands there, so a label-keyed allowlist would quietly strand
    a makerspace's own front-desk staff behind superadmin-only -- a permission *narrowing*
    delivered by an upgrade nobody asked for.

    So ask the question the guard was always a proxy for: does this membership already hold
    ``manage_makerspace``? That is the escalation the rule exists to stop, it is the same
    test `role_services.can_assign_role` applies to the same situation, and it is stable
    under a role being renamed or reshaped. Deliberately status-independent -- a revoked
    Space Manager is still a Space Manager membership, and re-attaching over one is exactly
    the case worth reserving for a superadmin.
    """
    if membership.assigned_role_id is not None:
        granted = membership.assigned_role.granted_actions
        return isinstance(granted, list) and rbac.Action.MANAGE_MAKERSPACE in granted
    # Null FK: the frozen legacy fallback. SPACE_MANAGER is the only legacy role whose
    # action set contains manage_makerspace, so the string answers it exactly.
    return membership.role == MakerspaceMembership.Role.SPACE_MANAGER


def _global_role_for_membership(legacy_role):
    # The GUEST_ADMIN branch is gone with the built-in role, and so is the enum member
    # itself (accounts `0009` rewrote the stored rows to `requester`, `0010` dropped the
    # choice). Removing it was safe because it gated nothing reachable: its only consumer
    # was `STAFF_ROLES`, read by `IsStaff`, whose sole `StaffAPIView` subclass overrides
    # `permission_classes`.
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
                # `of=("self",)` because `assigned_role` is nullable: select_related makes
                # it a LEFT OUTER JOIN, and Postgres refuses FOR UPDATE on the nullable
                # side of one. Same pattern as `role_services.assign_role`.
                existing = (
                    MakerspaceMembership.objects.select_for_update(of=("self",))
                    .select_related("assigned_role")
                    .filter(makerspace=makerspace, user=user)
                    .first()
                )
                if existing is not None and _is_superadmin_only_membership(existing):
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
