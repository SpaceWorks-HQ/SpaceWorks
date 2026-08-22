from dataclasses import dataclass

from django.db.models import Q

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership


@dataclass(frozen=True)
class TenantRepairRecipient:
    user: User
    receives_notifications: bool


def tenant_non_operator_repair_recipients(makerspace):
    """Return locally repair-capable users, excluding platform operators."""
    memberships = (
        MakerspaceMembership.objects.filter(
            makerspace=makerspace,
            status="active",
            user__is_active=True,
            user__access_status=User.AccessStatus.ACTIVE,
            user__must_change_password=False,
        )
        .exclude(Q(user__is_superuser=True) | Q(user__role=User.Role.SUPERADMIN))
        .select_related("user")
        .order_by("user_id", "pk")
    )
    recipients = []
    seen = set()
    for membership in memberships:
        user = membership.user
        if user.pk in seen:
            continue
        if rbac.Action.MANAGE_MAKERSPACE not in rbac.effective_actions(
            user, makerspace.pk
        ):
            continue
        seen.add(user.pk)
        recipients.append(
            TenantRepairRecipient(
                user=user,
                receives_notifications=membership.receives_notifications,
            )
        )
    return tuple(recipients)


def mailable_tenant_recipients(makerspace, repair_recipients):
    if not makerspace.staff_notifications_enabled:
        return ()
    return tuple(
        recipient.user
        for recipient in repair_recipients
        if recipient.receives_notifications and recipient.user.email.strip()
    )


def operator_recipients():
    return tuple(
        user
        for user in User.objects.filter(
            Q(is_superuser=True) | Q(role=User.Role.SUPERADMIN),
            is_active=True,
            access_status=User.AccessStatus.ACTIVE,
            must_change_password=False,
        )
        .exclude(email="")
        .order_by("pk")
        if user.email.strip()
    )


def alarm_message(makerspace, custody_state, recipient_count, *, operator):
    audience = "Platform operator" if operator else "Makerspace staff"
    subject = f"Archive custody alarm: {makerspace.name}"
    body = (
        f"{audience} custody warning. Makerspace: {makerspace.name} "
        f"({makerspace.slug}). State: {custody_state.state}. "
        f"Verified archive recipients: {recipient_count}. "
        f"Alarm revision: {custody_state.alarm_revision}. "
        "Review archive-recipient custody and restore redundancy. This message may "
        "repeat because custody-alarm delivery is at-least-once."
    )
    return subject, body
