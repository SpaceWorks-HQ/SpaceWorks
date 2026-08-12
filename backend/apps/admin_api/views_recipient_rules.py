"""Staff CRUD for per-event notification recipient selection."""

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.recipient_rule_access import payload as rules_payload
from apps.admin_api.recipient_rule_common import (
    RuleValidationError,
    reach_for,
    row_fully_reachable,
)
from apps.admin_api.recipient_rule_validation import prepare_rules
from apps.admin_api.recipient_rule_serializers import (
    RecipientRulesPutSerializer,
    RecipientRulesResponseSerializer,
)
from apps.integrations import notification_catalog, recipients as recipient_selection
from apps.integrations.notification_enums import NotificationFeature
from apps.integrations.recipient_rule_management import replace_recipient_rules
from apps.machines import role_scope
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled

DELEGATION_FEATURE = "notifications.delegated_recipients"


def _access(request, makerspace_id):
    makerspace = get_object_or_404(
        Makerspace.objects.filter(archived_at__isnull=True), pk=makerspace_id
    )
    if rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id):
        return makerspace, False, None
    if not (
        feature_enabled(makerspace, DELEGATION_FEATURE)
        and role_scope.is_machine_only(request.user, makerspace_id)
    ):
        raise PermissionDenied()
    reach = reach_for(request.user, makerspace_id)
    if reach is None:
        raise PermissionDenied()
    return makerspace, True, reach


@extend_schema(tags=["Makerspaces"], summary="Read or replace notification recipients")
class NotificationRecipientRulesView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "put", "head", "options"]

    @extend_schema(responses={200: RecipientRulesResponseSerializer})
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace, delegated, reach = _access(request, makerspace_id)
        return Response(
            rules_payload(
                makerspace, request.user, delegated=delegated, reach=reach
            )
        )

    @extend_schema(
        request=RecipientRulesPutSerializer,
        responses={
            200: RecipientRulesResponseSerializer,
            400: OpenApiResponse(description="Invalid recipient rule."),
            403: OpenApiResponse(description="Recipient-rule permission required."),
        },
    )
    def put(self, request, makerspace_id, *args, **kwargs):
        makerspace, delegated, reach = _access(request, makerspace_id)
        serializer = RecipientRulesPutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feature = serializer.validated_data["feature"]
        event = serializer.validated_data["event"]

        if feature not in recipient_selection.SELECTABLE_FEATURES:
            return self._error("This feature does not support recipient selection.")
        if delegated and feature != NotificationFeature.MAINTENANCE:
            raise PermissionDenied(
                "Delegated recipient management is limited to maintenance alerts."
            )
        if not recipient_selection.feature_available(makerspace, feature):
            return self._error(f"The {feature} module is not installed.")
        if event not in notification_catalog.FEATURE_EVENTS.get(feature, ()):
            return self._error(f"Unknown event '{event}' for feature '{feature}'.")

        try:
            prepared = prepare_rules(
                makerspace,
                serializer.validated_data["rules"],
                delegated=delegated,
                reach=reach,
                actor=request.user,
            )
            # A predicate, not a precomputed id list: the service resolves the partition
            # under the makerspace lock, so a concurrent PUT cannot leave this one
            # deleting a set that no longer describes the table. A Space Manager owns
            # every row; a delegated actor owns only what their reach fully covers.
            replace_recipient_rules(
                makerspace=makerspace,
                feature=feature,
                event=event,
                rules=prepared,
                keep_row=(
                    (lambda row: not row_fully_reachable(row, reach))
                    if delegated
                    else (lambda row: False)
                ),
                actor=request.user,
            )
        except RuleValidationError as exc:
            body = {"detail": exc.detail}
            if exc.unknown:
                body["unknown"] = exc.unknown
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            # A preserved Space Manager-owned row may already use the same recipient.
            # Refuse atomically rather than overwriting or silently narrowing it.
            return self._error(
                "A Space Manager-managed policy already uses one of these recipients."
            )

        return Response(
            rules_payload(
                makerspace, request.user, delegated=delegated, reach=reach
            )
        )

    @staticmethod
    def _error(detail):
        return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
