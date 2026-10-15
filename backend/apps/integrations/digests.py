"""Per-family opt-in email batching; safety mail never enters the batch."""

from datetime import time

from apps.accounts import rbac
from apps.makerspaces.platform import feature_enabled
from apps.notifications.models_inbox import MemberNotificationPreference


def digest_due(space, recipient_id, feature, now):
    if not recipient_id or not feature_enabled(space, 'notifications.digests'):
        return None
    from apps.integrations.quiet_hours import next_wall_time, timing_policy
    policy = timing_policy(space)
    pref = rbac.scope_notification_policy(MemberNotificationPreference.objects.all(), makerspace_id=space.pk).filter(
        user_id=recipient_id, feature=feature, channel='email',
    ).first()
    opted_in = pref.daily_digest and pref.enabled if pref else bool(policy and policy.daily_digest_default)
    if not opted_in:
        return None
    return next_wall_time(space, now, policy.digest_at if policy else time(8))
