from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.admin_api.serializers_payments import (
    PaymentSettingsErrorSerializer,
    PlatformStripeConnectSettingsSerializer,
)
from apps.audit import services as audit
from apps.makerspaces.domain_verification import is_self_host
from apps.payments.models import PlatformStripeConnectSettings

_ERRORS = {
    401: OpenApiResponse(PaymentSettingsErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(PaymentSettingsErrorSerializer, description="Superadmin only."),
    404: OpenApiResponse(PaymentSettingsErrorSerializer, description="Stripe Connect is dormant on a self-hosted deployment."),
}
_SUMMARY = "Retrieve or update platform Stripe Connect settings"


@extend_schema_view(
    get=extend_schema(
        tags=["Platform"], summary=_SUMMARY,
        responses={200: PlatformStripeConnectSettingsSerializer, **_ERRORS},
    ),
    patch=extend_schema(
        tags=["Platform"], summary=_SUMMARY,
        responses={
            200: PlatformStripeConnectSettingsSerializer,
            400: OpenApiResponse(OpenApiTypes.OBJECT, description="Field errors, including a credential change blocked by a live Connect session."),
            **_ERRORS,
        },
    ),
)
class PlatformStripeConnectSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformStripeConnectSettingsSerializer
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        if is_self_host():
            raise Http404
        return PlatformStripeConnectSettings.load()

    def perform_update(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request.user,
            "platform.stripe_connect_settings_updated",
            target=instance,
        )
