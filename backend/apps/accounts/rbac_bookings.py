"""Account-owned reservations remain private without inventing a membership."""

from apps.accounts.models import User
from apps.accounts.rbac_notifications import personal_notification_membership_refused
from apps.makerspaces.servability import servable_queryset


def scope_personal_bookings(actor, queryset, *, makerspace_id):
    if not (actor and actor.is_authenticated and actor.is_active
            and actor.access_status == User.AccessStatus.ACTIVE
            and not actor.is_tenant_dump_stub):
        return queryset.none()
    if type(makerspace_id) is not int or makerspace_id < 1:
        raise ValueError('Own bookings require a persisted makerspace id.')
    if personal_notification_membership_refused(actor, makerspace_id):
        return queryset.none()
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        from apps.accounts import rbac
        queryset = rbac.scope_by_makerspace(actor, queryset, makerspace_field='space__makerspace_id')
    return servable_queryset(queryset, relation='space__makerspace').filter(
        space__makerspace_id=makerspace_id, member=actor,
    )
