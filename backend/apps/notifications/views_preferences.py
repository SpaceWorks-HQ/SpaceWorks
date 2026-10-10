from django.core import signing
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.integrations.email_preferences import decode_unsubscribe
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.guards import require_module
from apps.makerspaces.servability import servable_queryset
from apps.notifications.access import personal_space
from apps.notifications.models_inbox import MemberNotificationPreference
from apps.notifications.preferences import channel_available, preference_cells
from apps.notifications.serializers_inbox import (
    PreferenceResponseSerializer, PreferenceWriteSerializer,
    UnsubscribeResultSerializer,
)
from apps.openapi_errors import errors
from apps.tenant_migration.gate_runtime import tenant_write


def save_preference(user, space, data, *, action="notification.preference_updated"):
    # Signed links resolve their tenant after HTTP middleware, so hold the late gate.
    with tenant_write(space.pk):
        rbac.scope_notification_policy(MemberNotificationPreference.objects.all(), makerspace_id=space.pk).update_or_create(
            user=user, makerspace=space, feature=data["feature"], channel=data["channel"],
            defaults={"enabled": data["enabled"]},
        )
        audit.record(user, action, makerspace=space, target=space, meta=data)


class MemberPreferenceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Personal notifications"], responses={200: PreferenceResponseSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        space = personal_space(request.user, makerspace_id, preferences=True)
        return Response({"cells": preference_cells(space, request.user)})

    @extend_schema(tags=["Personal notifications"], request=PreferenceWriteSerializer,
                   responses={200: PreferenceResponseSerializer, **errors(400, 401, 403, 404, 423, 503)})
    def patch(self, request, makerspace_id):
        space = personal_space(request.user, makerspace_id, preferences=True)
        serializer = PreferenceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["enabled"] and not channel_available(space, data["feature"], data["channel"]):
            raise ValidationError({"channel": "This family/channel is disabled by the makerspace."})
        save_preference(request.user, space, data)
        return Response({"cells": preference_cells(space, request.user)})


class OneClickUnsubscribeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, JSONParser]
    http_method_names = ["post", "options"]

    @extend_schema(tags=["Personal notifications"], auth=[], request={
        "type": "object", "required": ["List-Unsubscribe"],
        "properties": {"List-Unsubscribe": {"type": "string", "enum": ["One-Click"]}},
    }, responses={200: UnsubscribeResultSerializer, **errors(400, 404, 415, 423, 503)})
    def post(self, request, token):
        try:
            data = decode_unsubscribe(token)
        except (signing.BadSignature, TypeError, ValueError):
            raise ValidationError({"token": "Invalid or expired unsubscribe token."})
        if request.data.get("List-Unsubscribe") != "One-Click":
            raise ValidationError({"List-Unsubscribe": "Expected One-Click."})
        space = get_object_or_404(rbac.scope_notification_policy(
            servable_queryset(), makerspace_id=data["space"], field="pk",
        ))
        require_module(space, "notifications")
        if not feature_enabled(space, "notifications.member_preferences"):
            raise ValidationError({"feature": "Member preferences are disabled."})
        user = get_object_or_404(User, pk=data["user"], is_active=True, is_tenant_dump_stub=False)
        # The signature is the authority here; no browser login and no CSRF cookie.
        # Actor is the user who received the capability, never a provider/device.
        save_preference(user, space, {"feature": data["feature"], "channel": "email", "enabled": False},
                        action="notification.unsubscribed")
        return Response({"detail": "Optional emails for this family are disabled. Safety emails remain enabled."})
