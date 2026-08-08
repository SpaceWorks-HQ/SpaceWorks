"""Staff CRUD for per-event notification recipient selection.

Distinct from `views_notification_recipients`, which toggles an individual manager's
`receives_notifications` flag. This one answers "who should hear about THIS event",
which is the gap the mute model never covered for events, bookings, maintenance and
members.

The GET is deliberately fat: it returns the pickable roles, the selectable events and the
module-filtered feature list alongside the current selection, because the console cannot
render a picker without all four and splitting them costs a round trip per feature.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.admin_api.notification_scope import ScopeTargetError, apply_scope
from apps.audit import services as audit
from apps.integrations import notification_catalog, recipients as recipient_selection
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

SELECTABLE = sorted(recipient_selection.SELECTABLE_FEATURES)


class RecipientScopeSerializer(serializers.Serializer):
    machine_type_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    machine_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    category_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class RecipientRuleSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=NotificationRecipientKind.choices)
    role_id = serializers.IntegerField(required=False, allow_null=True)
    user_id = serializers.IntegerField(required=False, allow_null=True)
    scope = RecipientScopeSerializer(required=False)


class RecipientRulesPutSerializer(serializers.Serializer):
    feature = serializers.ChoiceField(choices=[(key, key) for key in SELECTABLE])
    event = serializers.CharField(max_length=64)
    rules = RecipientRuleSerializer(many=True)


def _makerspace(request, makerspace_id):
    require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
    return get_object_or_404(
        Makerspace.objects.filter(archived_at__isnull=True), pk=makerspace_id
    )


def _rows(makerspace):
    return NotificationRecipient.objects.filter(makerspace=makerspace).prefetch_related(
        "machine_scopes", "machine_type_scopes", "category_scopes"
    )


def _serialize_rule(row):
    return {
        "id": row.pk,
        "feature": row.feature,
        "event": row.event,
        "kind": row.kind,
        "role_id": row.role_id,
        "user_id": row.user_id,
        "scope": {
            "machine_type_ids": [link.machine_type_id for link in row.machine_type_scopes.all()],
            "machine_ids": [link.machine_id for link in row.machine_scopes.all()],
            "category_ids": [link.category_id for link in row.category_scopes.all()],
        },
    }


def _payload(makerspace):
    # Features whose module is uninstalled are omitted entirely (D14) — the same rule the
    # channel matrix follows. A picker for a feature that can never fire is a setting that
    # accepts input and does nothing.
    features = [
        {
            "key": feature,
            "events": list(notification_catalog.FEATURE_EVENTS.get(feature, ())),
        }
        for feature in SELECTABLE
        if recipient_selection.feature_available(makerspace, feature)
    ]
    roles = [
        {"id": role.pk, "name": role.name, "slug": role.slug}
        for role in MakerspaceRole.objects.filter(makerspace=makerspace).order_by("name")
    ]
    # Only members of THIS makerspace are offerable (D4). The picker and the send-time
    # resolver enforce the same rule, so the list can never suggest someone who would then
    # be filtered out.
    members = [
        {
            "id": membership.user_id,
            "username": membership.user.username,
            "email": membership.user.email,
        }
        for membership in MakerspaceMembership.objects.filter(
            makerspace=makerspace,
            status="active",
            user__is_active=True,
            user__access_status=User.AccessStatus.ACTIVE,
        )
        .exclude(user__is_superuser=True)
        .select_related("user")
        .order_by("user__username")
    ]
    return {
        "features": features,
        "roles": roles,
        "members": members,
        "rules": [_serialize_rule(row) for row in _rows(makerspace).order_by("feature", "event", "id")],
    }


@extend_schema(tags=["Makerspaces"], summary="Read or replace per-event notification recipients")
class NotificationRecipientRulesView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "put", "head", "options"]

    @extend_schema(responses={200: OpenApiResponse(description="Recipient selection.")})
    def get(self, request, makerspace_id, *args, **kwargs):
        return Response(_payload(_makerspace(request, makerspace_id)))

    @extend_schema(
        request=RecipientRulesPutSerializer,
        responses={
            200: OpenApiResponse(description="Recipient selection."),
            400: OpenApiResponse(description="Invalid recipient rule."),
        },
    )
    def put(self, request, makerspace_id, *args, **kwargs):
        """Replace the whole selection for ONE (feature, event).

        Replace rather than merge, for the same reason the machine-scope editor does:
        with a merge there is no way to untick the last recipient, and an empty list has
        to mean "nobody selected" rather than "no change". Deleting every rule for a
        (feature, event) returns it to the action-based default (D3).
        """
        makerspace = _makerspace(request, makerspace_id)
        payload = RecipientRulesPutSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        feature = payload.validated_data["feature"]
        event = payload.validated_data["event"]
        rules = payload.validated_data["rules"]

        if not recipient_selection.feature_available(makerspace, feature):
            return Response(
                {"detail": f"The {feature} module is not installed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if event not in notification_catalog.FEATURE_EVENTS.get(feature, ()):
            return Response(
                {"detail": f"Unknown event '{event}' for feature '{feature}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        error = self._validate(makerspace, rules)
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            NotificationRecipient.objects.filter(
                makerspace=makerspace, feature=feature, event=event
            ).delete()
            for rule in rules:
                row = NotificationRecipient.objects.create(
                    makerspace=makerspace,
                    feature=feature,
                    event=event,
                    kind=rule["kind"],
                    role_id=rule.get("role_id"),
                    user_id=rule.get("user_id"),
                    created_by=request.user,
                )
                try:
                    apply_scope(row, rule.get("scope"), makerspace)
                except ScopeTargetError as exc:
                    return Response(
                        {"detail": "Unknown scope target.", "unknown": exc.missing},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            audit.record(
                request.user,
                "notification.recipients_selected",
                makerspace=makerspace,
                target=makerspace,
                meta={
                    "feature": feature,
                    "event": event,
                    "kinds": [rule["kind"] for rule in rules],
                },
            )
        return Response(_payload(makerspace))

    def _validate(self, makerspace, rules):
        seen = set()
        for rule in rules:
            kind = rule["kind"]
            role_id = rule.get("role_id")
            user_id = rule.get("user_id")

            if kind == NotificationRecipientKind.ROLE:
                if role_id is None:
                    return "A role recipient needs a role."
                if not MakerspaceRole.objects.filter(
                    pk=role_id, makerspace=makerspace
                ).exists():
                    # Foreign roles are inert at send time anyway; refusing them here is
                    # what stops an operator believing a rule works when it matches nobody.
                    return "Role must belong to this makerspace."
                key = ("role", role_id)
            elif kind == NotificationRecipientKind.USER:
                if user_id is None:
                    return "A named recipient needs a user."
                if not MakerspaceMembership.objects.filter(
                    makerspace=makerspace, user_id=user_id, status="active"
                ).exists():
                    # D4: notification bodies carry requester names, machine detail and
                    # booking info. An external contractor gets a Member role first.
                    return "User must hold an active membership of this makerspace."
                key = ("user", user_id)
            else:
                if role_id is not None or user_id is not None:
                    return "Requester and all-member rows carry no role or user."
                key = (kind, None)

            if key in seen:
                return "Duplicate recipient in selection."
            seen.add(key)
        return None
