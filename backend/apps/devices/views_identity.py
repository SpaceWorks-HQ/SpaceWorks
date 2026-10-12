"""Staff device administration: list/create, detail/PATCH, new enrollment, revoke.

Authorization is action-based (`MANAGE_DEVICES`) and tenant-scoped through
``accounts.rbac`` BEFORE object lookup, so the list and a guessed detail URL can never
diverge: a device outside the actor's scope is a 404, not a 403. Every mutation goes
through a locked, audited service.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.devices import services_enrollment, services_identity
from apps.devices.errors import DeviceErrorSerializer
from apps.devices.models import Device
from apps.devices.serializers_identity import (
    DeviceCreatedSerializer,
    DeviceCreateSerializer,
    DeviceSerializer,
    DeviceUpdateSerializer,
    EnrollmentGrantSerializer,
)
from apps.makerspaces.guards import require_module

MODULE_KEY = "devices"
ERRORS = {
    400: OpenApiResponse(DeviceErrorSerializer, description="Invalid request or module disabled."),
    401: OpenApiResponse(DeviceErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(DeviceErrorSerializer, description="Permission denied."),
    404: OpenApiResponse(DeviceErrorSerializer, description="Not found."),
    423: OpenApiResponse(DeviceErrorSerializer, description="Tenant frozen for migration."),
}


def scoped_devices(actor):
    return rbac.scope_by_action(actor, rbac.Action.MANAGE_DEVICES, Device.objects.all())


def authorize(actor, makerspace_id):
    require_module(makerspace_id, MODULE_KEY)
    if not rbac.can(actor, rbac.Action.MANAGE_DEVICES, makerspace_id):
        raise PermissionDenied()


class DeviceObjectMixin:
    def device(self, request, pk):
        device = get_object_or_404(scoped_devices(request.user), pk=pk)
        authorize(request.user, device.makerspace_id)
        self.check_object_permissions(request, device)
        return device


@extend_schema(tags=["Devices"])
class DeviceListCreateView(generics.ListAPIView):
    serializer_class = DeviceSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        authorize(self.request.user, makerspace_id)
        return scoped_devices(self.request.user).filter(makerspace_id=makerspace_id).order_by("name", "id")

    @extend_schema(summary="List a makerspace's devices", responses={200: DeviceSerializer(many=True), **ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Create a pending device and its first enrollment",
        request=DeviceCreateSerializer,
        responses={201: DeviceCreatedSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id):
        authorize(request.user, makerspace_id)
        serializer = DeviceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device, enrollment, token = services_identity.create_device(
            request.user, makerspace_id, **serializer.validated_data
        )
        payload = {
            "device": DeviceSerializer(device).data,
            "enrollment": EnrollmentGrantSerializer(EnrollmentGrantSerializer.payload(enrollment, token)).data,
        }
        return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Devices"])
class DeviceDetailView(DeviceObjectMixin, APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(summary="Retrieve a device", responses={200: DeviceSerializer, **ERRORS})
    def get(self, request, pk):
        return Response(DeviceSerializer(self.device(request, pk)).data)

    @extend_schema(
        summary="Rename a device or change its offline threshold",
        request=DeviceUpdateSerializer,
        responses={200: DeviceSerializer, **ERRORS},
    )
    def patch(self, request, pk):
        device = self.device(request, pk)
        serializer = DeviceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = services_identity.update_device(request.user, device.pk, serializer.validated_data)
        return Response(DeviceSerializer(device).data)


@extend_schema(tags=["Devices"])
class DeviceEnrollmentCreateView(DeviceObjectMixin, APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        summary="Issue a new enrollment (enroll, rotate or reactivate by device status)",
        request=None,
        responses={201: EnrollmentGrantSerializer, **ERRORS},
    )
    def post(self, request, pk):
        device = self.device(request, pk)
        enrollment, token = services_enrollment.start_enrollment(request.user, device.pk)
        data = EnrollmentGrantSerializer(EnrollmentGrantSerializer.payload(enrollment, token)).data
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Devices"])
class DeviceRevokeView(DeviceObjectMixin, APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(summary="Revoke a device immediately", request=None, responses={200: DeviceSerializer, **ERRORS})
    def post(self, request, pk):
        device = services_identity.revoke_device(request.user, self.device(request, pk).pk)
        return Response(DeviceSerializer(device).data)
