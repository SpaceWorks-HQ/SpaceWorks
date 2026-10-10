"""Reminder recipients must currently manage the named machine or machine type.

Existing lifecycle selection semantics remain unchanged. Scheduled safety notices
require current authority even for an unconfigured role or a named recipient.
"""

from apps.accounts import rbac
from apps.makerspaces.models import MakerspaceMembership


def is_machine_reminder(feature, event):
    return feature in ("maintenance", "certifications") and event in ("due_soon", "overdue", "expiring", "expired")


def reminder_memberships(queryset, makerspace, feature, event):
    """Use the scheduler RBAC boundary only for the new timer events.

    Interactive lifecycle alerts keep the existing local-member delivery contract,
    including the intentional unconfigured-role fallback.
    """
    if is_machine_reminder(feature, event):
        return rbac.scope_for_scheduled_work(queryset, makerspace_id=makerspace.pk)
    return queryset


def reminder_staff_ids(makerspace, feature, event, scope):
    if not is_machine_reminder(feature, event):
        return None
    if scope is None:
        return set()
    from apps.machines import access
    from apps.machines.models import Machine, MachineType

    machine = rbac.scope_for_scheduled_work(
        Machine.objects.select_related("machine_type"), makerspace_id=makerspace.pk,
    ).filter(pk=scope.machine_id).first() if scope.machine_id else None
    from django.db.models import Q
    machine_type = MachineType.objects.filter(
        Q(makerspace__isnull=True) | Q(pk__in=rbac.scope_for_scheduled_work(
            MachineType.objects.all(), makerspace_id=makerspace.pk,
        ).values("pk")), pk=scope.machine_type_id,
    ).first() if scope.machine_type_id else None
    rows = rbac.scope_for_scheduled_work(
        MakerspaceMembership.objects.select_related("user"), makerspace_id=makerspace.pk,
    ).filter(status="active")
    return {row.user_id for row in rows if (
        access.can_manage_machine(row.user, machine) if machine else
        machine_type is not None and access.can_create_machine(row.user, makerspace.pk, machine_type)
    )}


def filter_reminder_emails(makerspace, feature, event, scope, emails):
    allowed = reminder_staff_ids(makerspace, feature, event, scope)
    if allowed is None:
        return emails
    from apps.accounts.models import User
    addresses = {email.lower() for email in User.objects.filter(pk__in=allowed).values_list("email", flat=True)}
    return [email for email in emails if email.lower() in addresses]
