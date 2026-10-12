"""Staff policy belongs to the core ledger, independently of provider settings."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.servability import servable_queryset
from apps.payments.models import MakerspaceBillingSettings
from apps.payments.schemas_billing import BILLING_POLICY_ERROR


class BillingSettingsSerializer(serializers.ModelSerializer):
    account_codes = serializers.JSONField(required=False)
    reminder_days_before = serializers.ListField(child=serializers.IntegerField(min_value=1, max_value=365), max_length=20)
    reminder_days_after = serializers.ListField(child=serializers.IntegerField(min_value=1, max_value=365), max_length=20)
    max_reminders = serializers.IntegerField(min_value=0, max_value=20)

    class Meta:
        model = MakerspaceBillingSettings
        fields = ("payment_terms_days", "reminder_days_before", "reminder_days_after", "max_reminders",
                  "number_prefix", "legal_name", "address", "tax_id", "footer", "account_codes")

    def validate_account_codes(self, value):
        from django.core.exceptions import ValidationError
        from apps.payments.models_billing import validate_account_codes
        try:
            validate_account_codes(value)
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def validate_number_prefix(self, value):
        if any(ord(char) < 32 or char in "/\\" for char in value):
            raise serializers.ValidationError("Use a prefix without control characters or slashes.")
        return value

    def validate(self, attrs):
        for name in ("reminder_days_before", "reminder_days_after"):
            if name in attrs and len(attrs[name]) != len(set(attrs[name])):
                raise serializers.ValidationError({name: "Reminder days must be distinct."})
        return attrs


ERRORS = {code: OpenApiResponse(ErrorSerializer) for code in (400, 401, 403, 404)}
ERRORS[400] = OpenApiResponse(BILLING_POLICY_ERROR, description="Invalid billing policy fields.")


class BillingSettingsView(APIView):
    permission_classes = [IsActiveStaff]

    def _space(self, request, makerspace_id):
        return get_object_or_404(rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_MAKERSPACE, servable_queryset(), field="pk",
        ), pk=makerspace_id)

    @extend_schema(tags=["Payments"], summary="Read billing, receipt and accounting policy",
                   description="Requires manage_makerspace. No payments module or credentials required; billing.reminders is a separate opt-in.",
                   responses={200: BillingSettingsSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = self._space(request, makerspace_id)
        policy = rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_MAKERSPACE, MakerspaceBillingSettings.objects.all(),
        ).filter(makerspace=space).first()
        return Response(BillingSettingsSerializer(policy or MakerspaceBillingSettings(makerspace=space)).data)

    @extend_schema(tags=["Payments"], summary="Change billing, receipt and accounting policy",
                   description="Requires manage_makerspace. Terms apply only to new charges. Reminders require billing.reminders, notifications and email; no online rail required.",
                   request=BillingSettingsSerializer, responses={200: BillingSettingsSerializer, **ERRORS})
    @transaction.atomic
    def patch(self, request, makerspace_id):
        space = self._space(request, makerspace_id)
        # Lock the always-present tenant before get_or_create serializes first writes.
        space = rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE,
                                     servable_queryset(), field="pk").select_for_update().get(pk=space.pk)
        policy, _ = rbac.scope_by_action(
            request.user, rbac.Action.MANAGE_MAKERSPACE, MakerspaceBillingSettings.objects.all(),
        ).get_or_create(makerspace=space)
        serializer = BillingSettingsSerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit.record(request.user, "payment.billing_policy_updated", makerspace=space,
                     target=space, meta={"fields": sorted(serializer.validated_data)})
        return Response(serializer.data)
