"""Staff CRUD for per-event notification recipient selection."""

from types import SimpleNamespace

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.recipient_rule_access import (
    _manageable_identity,
    payload as rules_payload,
)
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

        # A mutable holder so `keep_row` below sees the reach `revalidate` resolved under
        # the lock, not the one captured at closure-creation time.
        keep = SimpleNamespace(
            reach=reach,
            # The SAME identity gate the read uses. Without it the write partition is
            # scope-only, so a space manager's laser-scoped rule naming another role would
            # be hidden from the delegate by `payload` and still DELETED by their save --
            # the read/write disagreement, one level worse for being invisible.
            manageable=_manageable_identity(makerspace, request.user) if delegated else None,
        )

        def resolve(current_reach):
            return prepare_rules(
                makerspace,
                serializer.validated_data["rules"],
                delegated=delegated,
                reach=current_reach,
                actor=request.user,
            )

        def revalidate():
            """Re-resolve the delegate's authority under the makerspace lock.

            `_access` and `prepare_rules` both ran before the lock, so a space manager
            could have narrowed this role's machine scope in between; without this the
            request would write using reach the actor no longer holds.
            """
            if not delegated:
                return resolve(reach)
            _, still_delegated, fresh_reach = _access(request, makerspace_id)
            if not still_delegated or fresh_reach is None:
                raise PermissionDenied(
                    "Your recipient-management access changed while saving."
                )
            keep.reach = fresh_reach
            return resolve(fresh_reach)

        try:
            # Validated once up front so a bad payload is a 400 before any lock is taken,
            # then again under the lock by `revalidate`.
            prepared = resolve(reach)
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
                    # Reads `keep.reach`, which `revalidate` refreshes under the lock, so
                    # the preserved partition is decided by current authority rather than
                    # by what the view saw before waiting.
                    (
                        lambda row: not row_fully_reachable(
                            row, keep.reach, manageable_identity=keep.manageable
                        )
                    )
                    if delegated
                    else (lambda row: False)
                ),
                actor=request.user,
                revalidate=revalidate,
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
