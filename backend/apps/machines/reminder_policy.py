"""Shared tenant/type numeric settings, never the global capability_config."""

from apps.accounts import rbac
from django.db.models import Q
from .models import MakerspaceMachineTypePolicy


def policy_values(makerspace, machine_type_id):
    row = rbac.scope_for_scheduled_work(
        MakerspaceMachineTypePolicy.objects.all(), makerspace_id=makerspace.pk,
    ).filter(machine_type_id=machine_type_id).first()
    return {
        field: getattr(row, field) if row and getattr(row, field) is not None else default
        for field, default in (("cert_reminder_days", 14), ("reminder_lead_days", 7), ("grace_days", 0))
    }


def policy_window(makerspace, field, type_path, predicate):
    """Apply per-type windows BEFORE LIMIT, so a disabled early row cannot starve peers."""
    defaults = {"cert_reminder_days": 14, "reminder_lead_days": 7, "grace_days": 0}
    policies = rbac.scope_for_scheduled_work(
        MakerspaceMachineTypePolicy.objects.all(), makerspace_id=makerspace.pk,
    ).exclude(**{f"{field}__isnull": True})
    overrides = dict(policies.values_list("machine_type_id", field))
    condition = ~Q(**{f"{type_path}__in": list(overrides)}) & predicate(defaults[field])
    for type_id, days in overrides.items():
        condition |= Q(**{type_path: type_id}) & predicate(days)
    return condition
