"""Shared audited timing-policy writer for the staff editor and setup."""
from apps.accounts import rbac
from apps.admin_api.permissions import require_action
from apps.audit import services as audit
from apps.integrations.models_timing import NotificationTimingPolicy
from apps.integrations.serializers_timing import TimingPolicySerializer
from apps.makerspaces.guards import require_module_locked
from apps.tenant_migration.gate_runtime import tenant_write


def update_policy(actor, space, values):
    require_action(actor, rbac.Action.MANAGE_MAKERSPACE, space.pk)
    serializer = TimingPolicySerializer(data=values, partial=True)
    from apps.makerspaces.settings_validation import validate_settings as validate
    validate(serializer)
    with tenant_write(space.pk):
        space = require_module_locked(space, "notifications")
        policy = NotificationTimingPolicy.objects.filter(makerspace=space).select_for_update().first()
        policy = policy or NotificationTimingPolicy(makerspace=space)
        changed = []
        for name, value in serializer.validated_data.items():
            if name == "bounce_secret":
                policy.set_bounce_secret(value)
                changed.append(name)
            elif getattr(policy, name) != value:
                setattr(policy, name, value)
                changed.append(name)
        if changed or not policy.pk:
            policy.full_clean()
            policy.save()
            audit.record(actor, "notification.timing_updated", makerspace=space, target=policy,
                         meta={"fields": sorted(changed)})
    return policy
