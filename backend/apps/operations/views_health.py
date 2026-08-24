from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.operations.serializers import GenericObjectSerializer, HealthSerializer, ReadinessSerializer


class HealthView(APIView):
    permission_classes = [AllowAny]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Health"], summary="Health check", request=None, responses={200: HealthSerializer})
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    permission_classes = [AllowAny]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Health"], summary="Readiness check", request=None, responses={200: ReadinessSerializer})
    def get(self, request, *args, **kwargs):
        from django.conf import settings
        from apps.backup.host_readiness import HostReadinessError, assert_host_ready

        try:
            assert_host_ready(settings.SPACEWORKS_HOST_MARKER_PATH)
        except HostReadinessError as exc:
            return Response(
                {"status": "unavailable", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        from apps.encryption.readiness import assert_ready
        from apps.backup.readiness import archive_custody_readiness
        assert_ready()
        return Response(
            {
                "status": "ready",
                "database": "ok",
                "archive_custody": archive_custody_readiness(),
            }
        )
