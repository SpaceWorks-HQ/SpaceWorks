"""Device-side enrollment: challenge, then proof-of-possession completion.

No session or device authenticator runs here (``authentication_classes = []``): the
one-time enrollment token plus the signature over the server challenge IS the declared
``ENROLLMENT_TOKEN`` mode in ``route_registry``. Each view resolves only the
enrollment's makerspace, takes the late source gate for it, then calls the locked
service.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices import services_enrollment
from apps.devices.errors import DeviceErrorSerializer
from apps.devices.models import DeviceEnrollment
from apps.devices.permissions import DeviceRoutePermission
from apps.devices.serializers_identity import (
    ChallengeRequestSerializer,
    ChallengeResponseSerializer,
    CompleteRequestSerializer,
    DeviceIdentitySerializer,
)
from apps.tenant_migration.gate_runtime import assert_write_allowed

ERRORS = {
    code: OpenApiResponse(DeviceErrorSerializer, description=text)
    for code, text in (
        (400, "Malformed key, challenge or signature, or module disabled."),
        (401, "Not authenticated."),
        (403, "Enrollment credentials or proof of possession rejected."),
        (404, "Not found."),
        (409, "The key is already bound to another device, or rotation reused the key."),
        (410, "The enrollment was used, revoked or has expired."),
        (423, "Tenant frozen for migration."),
    )
}


def _enrollment_makerspace_id(pk):
    return DeviceEnrollment.objects.filter(pk=pk).values_list("makerspace_id", flat=True).first()


@extend_schema(tags=["Device protocol"], auth=[])
class DeviceEnrollmentChallengeView(APIView):
    authentication_classes = []
    permission_classes = [DeviceRoutePermission]

    @extend_schema(
        summary="Request a proof-of-possession challenge for a candidate key",
        request=ChallengeRequestSerializer,
        responses={200: ChallengeResponseSerializer, **ERRORS},
    )
    def post(self, request, pk):
        serializer = ChallengeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        makerspace_id = _enrollment_makerspace_id(pk)
        if makerspace_id is not None:
            assert_write_allowed(makerspace_id)
        challenge, expires_at = services_enrollment.issue_challenge(
            pk, serializer.validated_data["token"], serializer.validated_data["public_key"]
        )
        return Response(ChallengeResponseSerializer({"challenge": challenge, "expires_at": expires_at}).data)


@extend_schema(tags=["Device protocol"], auth=[])
class DeviceEnrollmentCompleteView(APIView):
    authentication_classes = []
    permission_classes = [DeviceRoutePermission]

    @extend_schema(
        summary="Complete enrollment by signing the challenge with the candidate key",
        request=CompleteRequestSerializer,
        responses={200: DeviceIdentitySerializer, **ERRORS},
    )
    def post(self, request, pk):
        serializer = CompleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        makerspace_id = _enrollment_makerspace_id(pk)
        if makerspace_id is not None:
            assert_write_allowed(makerspace_id)
        data = serializer.validated_data
        device = services_enrollment.complete_enrollment(
            pk, data["token"], data["public_key"], data["challenge"], data["signature"]
        )
        return Response(DeviceIdentitySerializer(device).data)
