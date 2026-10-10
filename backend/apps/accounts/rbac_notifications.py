"""Own notification history also admits account-only domain borrowers."""

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.servability import servable_queryset


def scope_notification_policy(queryset, *, makerspace_id, field="makerspace_id"):
    """Pin trusted delivery hygiene to its tenant, including archived custody mail.

    This is an internal outbox boundary, not authorization for an HTTP actor. Policy
    checks must keep suppressing bad addresses and opt-outs after runtime uninstall.
    HTTP callers must first authorize their User through the personal/staff scope.
    """
    if type(makerspace_id) is not int or makerspace_id < 1:
        raise ValueError("Notification policy requires a persisted makerspace id.")
    return queryset.filter(**{field: makerspace_id})


def scope_personal_notifications(actor, queryset):
    if not (actor and actor.is_authenticated and actor.is_active
            and actor.access_status == User.AccessStatus.ACTIVE
            and not actor.is_tenant_dump_stub):
        return queryset.none()
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        from apps.accounts import rbac
        queryset = rbac.scope_by_makerspace(actor, queryset)
    refused = MakerspaceMembership.objects.filter(user=actor).exclude(status="active")
    return servable_queryset(queryset, relation="makerspace").filter(user=actor).exclude(
        makerspace_id__in=refused.values("makerspace_id"),
    )


def personal_notification_membership_refused(actor, makerspace_id):
    """An organization staff grant must not undo a revoked personal membership."""
    return scope_notification_policy(
        MakerspaceMembership.objects.all(), makerspace_id=makerspace_id,
    ).filter(user=actor).exclude(status="active").exists()
