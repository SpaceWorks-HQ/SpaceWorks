"""Wall-clock delivery policy in the makerspace timezone, including DST gaps."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.accounts import rbac
from apps.integrations.models_timing import NotificationTimingPolicy
from apps.makerspaces.local_time import _wall_bound, to_local
from apps.makerspaces.platform import feature_enabled


def timing_policy(space):
    return rbac.scope_notification_policy(NotificationTimingPolicy.objects.all(), makerspace_id=space.pk).first()


def next_wall_time(space, at, clock):
    local = to_local(space, at)
    day = local.date()
    zone = ZoneInfo(space.timezone)
    bound = _wall_bound(zone, datetime.combine(day, clock), closing=True)
    if bound <= at:
        bound = _wall_bound(zone, datetime.combine(day + timedelta(days=1), clock), closing=True)
    return bound


def quiet_until(space, channel, at):
    if not feature_enabled(space, 'notifications.quiet_hours'):
        return None
    policy = timing_policy(space)
    if policy is None or channel not in policy.channels or policy.quiet_start == policy.quiet_end:
        return None
    clock = to_local(space, at).time().replace(tzinfo=None)
    start, end = policy.quiet_start, policy.quiet_end
    inside = start <= clock < end if start < end else clock >= start or clock < end
    return next_wall_time(space, at, end) if inside else None
