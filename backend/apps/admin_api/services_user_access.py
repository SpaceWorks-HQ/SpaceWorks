from dataclasses import dataclass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.crypto import get_random_string
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import hidden_space_manager_reset_break_glass
from apps.audit import services as audit
from apps.makerspaces.models import MakerspaceMembership


@dataclass(frozen=True)
class PasswordResetResult:
    user: User
    temporary_password: str


def reset_user_password(actor, target_pk, password=None, data=None):
    is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
    target = _target_for_reset(actor, target_pk, is_superadmin)
    if target.is_superuser or target.role == User.Role.SUPERADMIN:
        raise PermissionDenied("Cannot reset a superadmin's password here.")
    # A walk-in is a person record staff typed at the counter, not an account, and this
    # service HANDS BACK a usable temporary password -- so without this it is a one-click
    # way to turn one into a login, available to any space manager in the makerspace and
    # strictly easier than the forgot-password route the `is_walk_in` flag was added to
    # close. Refused in the shared service rather than the view, because the Django admin
    # action calls it too and a check in one place would leave the other open. Turning a
    # walk-in into an account is a `MANAGE_MAKERSPACE` decision about identity, not a
    # password operation; the person should sign up and be invited.
    if target.is_walk_in:
        raise PermissionDenied(
            "This is a walk-in record, not an account. It has no password to reset."
        )

    break_glass_password_reset = False
    if is_superadmin:
        break_glass_password_reset = hidden_space_manager_reset_break_glass(target)
    _require_non_superadmin_reset_scope(actor, target, is_superadmin)

    if data is not None:
        from apps.admin_api.serializers_users import ResetPasswordRequestSerializer

        serializer = ResetPasswordRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data.get("password")

    temporary_password = _validated_or_generated_password(password, target)
    with transaction.atomic():
        # Close the stale-read interleaving where the walk-in migration marks this
        # user after the check above but before this password write.
        target = User.objects.select_for_update().get(pk=target.pk)
        if target.is_walk_in:
            raise PermissionDenied(
                "This is a walk-in record, not an account. It has no password to reset."
            )
        target.set_password(temporary_password)
        target.must_change_password = True
        target.save(update_fields=["password", "must_change_password"])

    from apps.accounts.services_tokens import blacklist_outstanding_tokens

    blacklist_outstanding_tokens(target)
    audit.record(
        actor,
        (
            "superadmin.break_glass_space_manager_password_reset"
            if break_glass_password_reset
            else "user.password_reset"
        ),
        target=target,
        meta={"by_superadmin": is_superadmin},
    )
    return PasswordResetResult(user=target, temporary_password=temporary_password)


def _target_for_reset(actor, pk, is_superadmin):
    if is_superadmin:
        return get_object_or_404(User, pk=pk)
    scope = rbac.makerspaces_for_action(actor, rbac.Action.MANAGE_MAKERSPACE)
    base = User.objects.all()
    if scope is not rbac.ALL:
        base = base.filter(makerspace_memberships__makerspace_id__in=scope).distinct()
    return get_object_or_404(base, pk=pk)


def _require_non_superadmin_reset_scope(actor, target, is_superadmin):
    if is_superadmin:
        return
    memberships = MakerspaceMembership.objects.filter(user=target)
    if not memberships.exists():
        raise PermissionDenied("You can only reset staff in your makerspaces.")
    scope = rbac.makerspaces_for_action(actor, rbac.Action.MANAGE_MAKERSPACE)
    if scope is not rbac.ALL:
        target_ms = set(memberships.values_list("makerspace_id", flat=True))
        if not target_ms.issubset(scope):
            raise PermissionDenied(
                "This user also belongs to a makerspace outside your authority."
            )
    for membership in memberships:
        if rbac.can(
            target, rbac.Action.MANAGE_MAKERSPACE, membership.makerspace_id
        ):
            raise PermissionDenied("Cannot reset another Space Manager's password.")


def _validated_or_generated_password(password, target):
    if password:
        try:
            validate_password(password, user=target)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc
        return password
    for _ in range(5):
        candidate = get_random_string(12)
        try:
            validate_password(candidate, user=target)
            return candidate
        except DjangoValidationError:
            continue
    return get_random_string(16)
