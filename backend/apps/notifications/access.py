from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.servability import servable_queryset
from apps.notifications.models_inbox import NotificationInboxRow


def personal_space(user, makerspace_id, *, preferences=False):
    if not (user.is_active and user.access_status == User.AccessStatus.ACTIVE and not user.is_tenant_dump_stub):
        raise PermissionDenied()
    if rbac.personal_notification_membership_refused(user, makerspace_id):
        raise PermissionDenied()
    space = get_object_or_404(rbac.scope_notification_policy(
        servable_queryset(), makerspace_id=makerspace_id, field="pk",
    ))
    membership = rbac.scope_by_makerspace(user, MakerspaceMembership.objects.all()).filter(
        makerspace=space, user=user, status="active",
    ).first()
    # A debt/loan owner without membership can reach rows written specifically to them.
    owned = rbac.scope_personal_notifications(user, NotificationInboxRow.objects.all()).filter(
        makerspace=space,
    ).exists()
    if membership is None and not owned and not rbac.effective_actions(user, space.pk):
        raise PermissionDenied()
    require_module(space, "notifications")
    key = "notifications.member_preferences" if preferences else "notifications.member_inbox"
    # Staff can always reach their personal inbox. Member feature gates stay opt-in.
    if (preferences or not rbac.effective_actions(user, space.pk)) and not feature_enabled(space, key):
        raise ValidationError({"feature": f"{key} is disabled for this makerspace."})
    return space
