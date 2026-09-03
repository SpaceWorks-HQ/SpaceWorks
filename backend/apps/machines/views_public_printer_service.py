from types import SimpleNamespace
import uuid

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.machines.models import MachineServiceRequest
from apps.machines.public_printer_service import public_pools, public_queues, public_status, stage_upload, submit_request
from apps.machines.public_printer_service_serializers import PublicPrinterPoolSerializer, PublicPrinterQueueSerializer, PublicPrinterStatusSerializer, PublicPrinterSubmitResponseSerializer, PublicPrinterSubmitSerializer, PublicPrinterUploadSerializer
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.machines.views_public_service import require_public_machine_requester
from apps.machines.permissions import IsActiveRequester


def _require_printer_module(makerspace):
    """The public printer surface belongs to `printing`, which is separately optional.

    This gated on `machine_service` instead, so the RECOMMENDED profile -- which ships
    `machine_service` ON and `printing` OFF -- exposed the entire public printer API for a
    module the operator had explicitly left off. `printing` already declares
    `requires_modules=("machine_service",)`, so the dependency runs the other way and
    checking `printing` alone is both necessary and sufficient.
    """
    if not module_enabled(makerspace, "printing"):
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"module": "printing is disabled for this makerspace."})


class PublicPrinterQueuesView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(tags=["Public machine service"], auth=[], responses={200: PublicPrinterQueueSerializer(many=True)})
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        return Response(PublicPrinterQueueSerializer(public_queues(makerspace), many=True).data)


class PublicPrinterPoolsView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(tags=["Public machine service"], auth=[], responses={200: PublicPrinterPoolSerializer(many=True)})
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        return Response(PublicPrinterPoolSerializer(public_pools(makerspace), many=True).data)


class PublicPrinterUploadView(APIView):
    permission_classes = [IsActiveRequester]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "print_request_submit"

    @extend_schema(tags=["Public machine service"], request=PublicPrinterUploadSerializer, responses={201: PublicPrinterSubmitResponseSerializer})
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        require_public_machine_requester(request.user, makerspace)
        serializer = PublicPrinterUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(stage_upload(makerspace, serializer.validated_data, request.user), status=status.HTTP_201_CREATED)


class PublicPrinterRequestView(APIView):
    permission_classes = [IsActiveRequester]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "print_request_submit"

    @extend_schema(tags=["Public machine service"], request=PublicPrinterSubmitSerializer, responses={201: PublicPrinterSubmitResponseSerializer})
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        _require_printer_module(makerspace)
        if str(request.data.get("website", "")).strip():
            decoy = SimpleNamespace(public_token=uuid.uuid4(), status=MachineServiceRequest.Status.PENDING)
            return Response(PublicPrinterSubmitResponseSerializer(decoy).data, status=status.HTTP_201_CREATED)
        require_public_machine_requester(request.user, makerspace)
        serializer = PublicPrinterSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = submit_request(makerspace, serializer.validated_data, request.user)
        return Response(PublicPrinterSubmitResponseSerializer(row).data, status=status.HTTP_201_CREATED)


class PublicPrinterStatusView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "request_status"

    @extend_schema(tags=["Public machine service"], auth=[], responses={200: PublicPrinterStatusSerializer})
    def get(self, request, public_token):
        row, counts = public_status(public_token)
        return Response(PublicPrinterStatusSerializer(row, context={"queue_counts": counts}).data)