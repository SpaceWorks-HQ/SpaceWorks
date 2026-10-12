import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.openapi_errors import errors
from apps.accounts.views_device import IsDeviceAccessToken
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.integrations.models_push import PushDevice
from apps.integrations.serializers_push import PushDeviceRegistrationSerializer, PushDeviceSerializer
from apps.makerspaces.origin_scope import require_native_selected_makerspace


def _fingerprint(provider, environment, raw):
    key = settings.PUSH_TOKEN_HMAC_KEY
    if not key or len(key) < 32:
        raise RuntimeError("push token fingerprinting is not configured")
    value = f"{provider}\0{environment}\0{raw}".encode()
    return hmac.new(key.encode(), value, hashlib.sha256).hexdigest()


class PushDeviceListCreateView(APIView):
    permission_classes = [IsDeviceAccessToken]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "push_device_registration"

    @extend_schema(tags=["Native push"], request=PushDeviceRegistrationSerializer,
        responses={200: PushDeviceSerializer, 201: PushDeviceSerializer, **errors(400, 401, 403, 409, 429, 503)})
    def post(self, request):
        membership = require_native_selected_makerspace(request)
        serializer = PushDeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        expected_provider = "apns" if request.device_grant.platform == "apple" else "fcm"
        if data["provider"] != expected_provider or data["environment"] != request.device_grant.environment:
            return Response({"detail": "Push identity does not match the attested device.", "code": "push_identity_mismatch"}, status=403)
        try:
            fingerprint = _fingerprint(data["provider"], data["environment"], data["token"])
            with transaction.atomic():
                device = PushDevice.objects.select_for_update().filter(
                    makerspace_id=membership.makerspace_id,
                    provider=data["provider"], environment=data["environment"],
                    token_fingerprint=fingerprint,
                ).first()
                created = device is None
                if device is not None and device.user_id != request.user.pk:
                    return Response(
                        {
                            'detail': 'The push token is owned by another account.',
                            'code': 'push_token_ownership_conflict',
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                device = device or PushDevice(
                    makerspace_id=membership.makerspace_id,
                    provider=data["provider"], environment=data["environment"],
                    token_fingerprint=fingerprint,
                )
                device.user = request.user
                device.device_grant = request.device_grant
                device.active = True
                device.invalidated_at = None
                device.set_token(data["token"])
                device.save()
                audit.record(
                    request.user,
                    'push.device_registered',
                    makerspace=membership.makerspace,
                    target=device,
                    meta={
                        'provider': device.provider,
                        'environment': device.environment,
                    },
                )
        except Exception:
            return Response({"detail": "Push registration is unavailable.", "code": "push_unavailable"}, status=503)
        return Response(PushDeviceSerializer(device).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PushDeviceDetailView(APIView):
    permission_classes = [IsDeviceAccessToken]

    @extend_schema(tags=["Native push"], request=None,
        responses={204: None, 401: OpenApiResponse(ErrorSerializer), 403: OpenApiResponse(ErrorSerializer), 404: OpenApiResponse(ErrorSerializer)})
    def delete(self, request, device_id):
        membership = require_native_selected_makerspace(request)
        device = PushDevice.objects.filter(
            pk=device_id, user=request.user,
            makerspace_id=membership.makerspace_id,
        ).first()
        if device is None:
            return Response(status=404)
        with transaction.atomic():
            device.active = False
            device.invalidated_at = timezone.now()
            device.save(update_fields=["active", "invalidated_at", "updated_at"])
            audit.record(
                request.user,
                'push.device_deleted',
                makerspace=membership.makerspace,
                target=device,
                meta={'provider': device.provider},
            )
        return Response(status=204)
