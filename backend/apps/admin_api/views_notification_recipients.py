from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.openapi_errors import errors

# Actions that make a membership eligible for staff lifecycle notifications
# (union of the per-feature required actions in staff_notifications._FEATURE_ACTIONS:
# hardware=accept_request, printing=manage_printing, events=manage_events,
# bookings=manage_bookings, maintenance=manage_machines). Eligibility is action-based
# so custom roles are surfaced here exactly when they receive the emails, keeping this
# management endpoint in lockstep with staff_emails_for_feature.
NOTIFY_ACTIONS = frozenset({
    rbac.Action.ACCEPT_REQUEST,
    rbac.Action.MANAGE_PRINTING,
    rbac.Action.MANAGE_EVENTS,
    rbac.Action.MANAGE_BOOKINGS,
    rbac.Action.MANAGE_MACHINES,
})


class NotificationRecipientSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True, allow_blank=True)
    role = serializers.CharField(read_only=True)
    receives_notifications = serializers.BooleanField()


class NotificationRecipientUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    receives_notifications = serializers.BooleanField()


class NotificationRecipientsPatchSerializer(serializers.Serializer):
    recipients = NotificationRecipientUpdateSerializer(many=True)


@extend_schema(tags=["Makerspaces"], summary="List or toggle staff email notification recipients")
class NotificationRecipientsView(APIView):
    """Space-manager control over which of the makerspace's managers receive the staff
    lifecycle emails. Toggling a manager off clears `receives_notifications` without
    touching their access/role."""

    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def _makerspace(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
        return get_object_or_404(Makerspace, pk=makerspace_id)

    def _queryset(self, makerspace):
        # Action-based eligibility: a membership is a notification recipient when its
        # effective actions include any NOTIFY_ACTIONS. actions_for_membership needs the
        # assigned_role JSON, so we resolve eligibility in Python then re-filter to keep a
        # queryset (the PATCH path calls .filter(id__in=...) on this).
        base = (
            MakerspaceMembership.objects.filter(
                makerspace=makerspace,
                user__is_active=True,
                user__access_status=User.AccessStatus.ACTIVE,
            )
            .exclude(user__is_superuser=True)
            .exclude(user__role=User.Role.SUPERADMIN)
            .select_related("user", "assigned_role")
        )
        eligible_ids = [
            membership.id
            for membership in base
            if rbac.actions_for_membership(membership) & NOTIFY_ACTIONS
        ]
        return (
            base.filter(id__in=eligible_ids)
            .order_by("role", "user__username", "id")
        )

    @extend_schema(
        responses={
            200: NotificationRecipientSerializer(many=True),
            **errors(401, 403, 404),
        }
    )
    def get(self, request, *args, **kwargs):
        makerspace = self._makerspace()
        data = NotificationRecipientSerializer(self._queryset(makerspace), many=True).data
        return Response(data)

    @extend_schema(
        request=NotificationRecipientsPatchSerializer,
        responses={
            200: NotificationRecipientSerializer(many=True),
            **errors(400, 401, 403, 404),
        },
    )
    def patch(self, request, *args, **kwargs):
        makerspace = self._makerspace()
        payload = NotificationRecipientsPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        updates = {row["id"]: row["receives_notifications"] for row in payload.validated_data["recipients"]}
        # Scope updates to THIS makerspace's eligible memberships only — an id from another
        # tenant or a non-notify role is silently ignored, never updated.
        memberships = list(self._queryset(makerspace).filter(id__in=updates))
        changed = []
        for membership in memberships:
            new_value = updates[membership.id]
            if membership.receives_notifications != new_value:
                membership.receives_notifications = new_value
                changed.append(membership)
        if changed:
            MakerspaceMembership.objects.bulk_update(changed, ["receives_notifications"])
            audit.record(
                request.user,
                "makerspace.notification_recipients_updated",
                makerspace=makerspace,
                target=makerspace,
                meta={"changed": {str(m.id): m.receives_notifications for m in changed}},
            )
        data = NotificationRecipientSerializer(self._queryset(makerspace), many=True).data
        return Response(data, status=status.HTTP_200_OK)
