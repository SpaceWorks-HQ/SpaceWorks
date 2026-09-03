import uuid
from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines import service_workflow
from apps.machines.models import Machine, MachineServiceRequest
from apps.machines.public_service_serializers import (
    PublicMachineServiceSubmitResponseSerializer,
    PublicMachineServiceSubmitSerializer,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.presence.guard import require_active_account, require_active_member_presence


SERVICE_SUBMIT_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid machine service request input."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication is required."),
    403: OpenApiResponse(ErrorSerializer, description="Active membership, waiver acceptance, and presence are required."),
    404: OpenApiResponse(ErrorSerializer, description="Makerspace or machine not found."),
    409: OpenApiResponse(ErrorSerializer, description="Machine service request conflict."),
    429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
}


def require_public_machine_requester(user, makerspace):
    """Same identity contract as the public BORROW request, for the same reason.

    A machine-service or print request is a PROPOSAL that staff act on -- the requester is
    asking for a job to be run, not operating the machine themselves -- so it must not
    hard-require a MakerspaceMembership row. Doing so made the surface dead for every
    ordinary account on the default `recommended` profile, which ships `machine_service`
    with `membership` off.

    Mirrors `apps/hardware_requests/public_views.py`: membership, waiver and presence when
    the community module is installed; an active account when it is not, because waiver
    acceptance lives on MakerspaceMembership and cannot be recorded at all without it.
    """
    if module_enabled(makerspace, "membership"):
        return require_active_member_presence(user, makerspace)
    return require_active_account(user, makerspace)

class PublicMachineServiceSubmitView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_request_submit"

    @extend_schema(
        tags=["Public machine service"],
        summary="Submit a machine service request as a member",
        request=PublicMachineServiceSubmitSerializer,
        responses={201: PublicMachineServiceSubmitResponseSerializer, **SERVICE_SUBMIT_ERRORS},
    )
    def post(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module(makerspace, "machine_service")
        require_public_machine_requester(request.user, makerspace)
        if _honeypot_filled(request.data):
            decoy = SimpleNamespace(
                public_token=uuid.uuid4(), status=MachineServiceRequest.Status.PENDING,
            )
            return Response(
                PublicMachineServiceSubmitResponseSerializer(decoy).data,
                status=status.HTTP_201_CREATED,
            )
        serializer = PublicMachineServiceSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        machine = get_object_or_404(
            Machine.objects.filter(makerspace=makerspace, is_active=True),
            pk=data["machine_id"],
        )
        service_request = service_workflow.submit(
            machine,
            request.user,
            member=request.user,
            actor=request.user,
            requester_name=request.user.display_name,
            contact_email=request.user.email,
            contact_phone=request.user.phone,
            title=data["title"],
            description=data.get("description", ""),
            source_link=data.get("source_link", ""),
            capability_payload=data.get("capability_payload"),
        )
        return Response(
            PublicMachineServiceSubmitResponseSerializer(service_request).data,
            status=status.HTTP_201_CREATED,
        )


def _honeypot_filled(payload):
    try:
        value = payload.get("website", "")
    except AttributeError:
        return False
    return bool(str(value).strip())
