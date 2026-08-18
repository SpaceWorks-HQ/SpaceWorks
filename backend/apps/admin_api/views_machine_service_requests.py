"""Staff list, detail, and intake views for machine-service requests."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_service import (
    MachineServiceRequestSerializer,
    MachineServiceSubmitSerializer,
)
from apps.admin_api.views_machine_service_common import (
    SERVICE_ERRORS,
    SERVICE_FILTERS,
    _query_int,
    _read_or_collect_queryset,
    _readable_or_collectable_request,
    _response,
    _visible_makerspace,
)
from apps.machines import role_scope, service_workflow
from apps.machines.models import Machine
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment


class MachineServiceRequestListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"],
        summary="List machine service requests",
        parameters=SERVICE_FILTERS,
        responses={200: MachineServiceRequestSerializer(many=True), **SERVICE_ERRORS},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(
            request.user, makerspace_id, rbac.Action.COLLECT_SERVICE_REQUEST
        )
        rows = _read_or_collect_queryset(request.user, makerspace.pk)
        status_value = request.query_params.get("status")
        if status_value not in (None, ""):
            rows = rows.filter(status=status_value)
        for name, field in (
            ("machine", "bucket__machine_id"),
            ("bucket", "bucket_id"),
            ("queue", "queue_id"),
        ):
            if value := _query_int(request, name):
                rows = rows.filter(**{field: value})
        # The id is preferred: slugs are unique only within the global/tenant split.
        if machine_type_id := _query_int(request, "machine_type_id"):
            rows = rows.filter(
                Q(queue__machine_type_id=machine_type_id)
                | Q(bucket__machine__machine_type_id=machine_type_id)
            )
        elif machine_type := request.query_params.get("machine_type"):
            rows = rows.filter(
                Q(queue__machine_type__slug=machine_type)
                | Q(bucket__machine__machine_type__slug=machine_type)
            )
        rows = list(rows.order_by("-created_at"))
        payments = Payment.objects.filter(
            makerspace=makerspace,
            subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
            subject_id__in=[row.pk for row in rows],
        )
        payment_map = {payment.subject_id: payment for payment in payments}
        return Response(
            MachineServiceRequestSerializer(
                rows,
                many=True,
                context={"payments_by_subject_id": payment_map},
            ).data
        )

    @extend_schema(
        tags=["Admin machine service"],
        summary="Submit a machine service request for a member",
        request=MachineServiceSubmitSerializer,
        responses={201: MachineServiceRequestSerializer, **SERVICE_ERRORS},
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        serializer = MachineServiceSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = get_object_or_404(
            MakerspaceMembership.objects.select_related("user").filter(
                makerspace=makerspace,
                status="active",
                user_id=data["requester_id"],
                user__is_active=True,
                user__access_status=User.AccessStatus.ACTIVE,
            )
        )
        machine = get_object_or_404(
            Machine.objects.filter(
                role_scope.scoped_q(request.user, [makerspace.pk]),
                makerspace=makerspace,
            ),
            pk=data["machine_id"],
        )
        requester = member.user
        row = service_workflow.submit(
            machine,
            requester,
            actor=request.user,
            member=requester,
            requester_name=(
                data.get("requester_name")
                or requester.get_full_name().strip()
                or requester.username
            ),
            contact_email=data.get("contact_email") or requester.email,
            contact_phone=data.get("contact_phone") or requester.phone,
            title=data["title"],
            description=data.get("description", ""),
            source_link=data.get("source_link", ""),
            capability_payload=data.get("capability_payload"),
        )
        return _response(row, status.HTTP_201_CREATED)


class MachineServiceRequestDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"],
        summary="Retrieve a machine service request",
        responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        return _response(_readable_or_collectable_request(request.user, pk))
