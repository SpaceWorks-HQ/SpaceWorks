from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_payments import (
    MakerspacePaymentSettingsSerializer,
    PaymentSettingsErrorSerializer,
    StripeConnectOnboardingSerializer,
)
from apps.audit import services as audit
from apps.makerspaces.domain_verification import is_self_host
from apps.makerspaces.servability import servable_queryset
from apps.payments.connect import create_onboarding
from apps.payments.models import MakerspacePaymentSettings
from apps.payments.stripe_client import PaymentsUnavailable
from rest_framework import status


class MakerspacePaymentSettingsView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def _makerspace(self, request, makerspace_id):
        return get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )

    @extend_schema(
        tags=["Admin payment settings"],
        summary="Retrieve makerspace payment settings",
        responses={
            200: MakerspacePaymentSettingsSerializer,
            403: PaymentSettingsErrorSerializer,
            404: PaymentSettingsErrorSerializer,
        },
    )
    def get(self, request, makerspace_id):
        makerspace = self._makerspace(request, makerspace_id)
        payment_settings = MakerspacePaymentSettings.for_makerspace(makerspace)
        return Response(MakerspacePaymentSettingsSerializer(payment_settings).data)

    @extend_schema(
        tags=["Admin payment settings"],
        summary="Update makerspace payment settings",
        request=MakerspacePaymentSettingsSerializer,
        responses={
            200: MakerspacePaymentSettingsSerializer,
            400: OpenApiResponse(description="Invalid payment settings."),
            403: PaymentSettingsErrorSerializer,
            404: PaymentSettingsErrorSerializer,
        },
    )
    def patch(self, request, makerspace_id):
        makerspace = self._makerspace(request, makerspace_id)
        payment_settings, _ = MakerspacePaymentSettings.objects.get_or_create(
            makerspace=makerspace
        )
        serializer = MakerspacePaymentSettingsSerializer(
            payment_settings, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        audit.record(
            request.user,
            "payments.settings_updated",
            makerspace=makerspace,
            target=updated,
        )
        return Response(MakerspacePaymentSettingsSerializer(updated).data)


class StripeConnectOnboardingView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(
        tags=["Admin payment settings"],
        summary="Start Stripe Connect onboarding",
        request=None,
        responses={
            200: StripeConnectOnboardingSerializer,
            403: PaymentSettingsErrorSerializer,
            404: PaymentSettingsErrorSerializer,
            503: PaymentSettingsErrorSerializer,
        },
    )
    def post(self, request, makerspace_id):
        if is_self_host():
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        makerspace = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        try:
            authorize_url = create_onboarding(makerspace, request.user)
        except PaymentsUnavailable:
            return Response(
                {"detail": "Stripe Connect is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        audit.record(
            request.user,
            "payments.connect_onboarding_started",
            makerspace=makerspace,
            target=makerspace,
        )
        return Response({"authorize_url": authorize_url})
