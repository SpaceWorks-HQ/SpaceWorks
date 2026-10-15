"""Shared machine-type reminder settings, retaining the existing editor's contract."""
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit.services import record
from apps.makerspaces.guards import require_module_locked
from apps.tenant_migration.gate_runtime import assert_write_allowed
from .models import MakerspaceMachineTypePolicy


@transaction.atomic
def update_policy(actor, space, machine_type, values):
    from apps.admin_api.views_machine_type_policy import MachineTypePolicySerializer
    assert_write_allowed(space.pk)
    space = require_module_locked(space, "machines")
    if not rbac.is_space_manager_identity(actor, space.pk):
        raise PermissionDenied()
    if machine_type.makerspace_id not in (None, space.pk):
        raise ValidationError("Machine type is outside this makerspace.")
    serializer = MachineTypePolicySerializer(data=values)
    from apps.makerspaces.settings_validation import validate_settings
    validate_settings(serializer)
    row = MakerspaceMachineTypePolicy.objects.filter(makerspace=space, machine_type=machine_type).first()
    row = row or MakerspaceMachineTypePolicy(makerspace=space, machine_type=machine_type)
    changed = []
    for name, value in serializer.validated_data.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed.append(name)
    if changed or not row.pk:
        row.full_clean()
        row.save()
        record(actor, "machine_type.policy_updated", makerspace=space, target=row,
               meta={"fields": sorted(changed)})
    return row
