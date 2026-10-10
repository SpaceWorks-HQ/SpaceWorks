from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.devices.authentication import DeviceAuthentication
from apps.devices.errors import DeviceErrorSerializer
from apps.devices.label_access import authorize_staff, scoped_batches
from apps.devices.models import LabelPrintCommand
from apps.devices.permissions import DeviceRoutePermission
from apps.devices.serializers_labels import (
    LabelCommandSerializer, LabelCreateSerializer, LabelReceiptSerializer, LabelResultSerializer,
)
from apps.devices.services_label_commands import create_label_command
from apps.devices.services_label_delivery import command_content
from apps.devices.services_label_results import report_result

LABEL_ERRORS = {code: OpenApiResponse(DeviceErrorSerializer, description=text)
    for code, text in [(400, "Invalid request or adapter module disabled."),
        (401, "Authentication required or invalid signature."), (403, "Permission denied."),
        (404, "Command or batch not in scope."), (409, "Idempotency or delivery conflict."),
        (410, "Batch no longer available."), (423, "Tenant frozen for migration.")]}
LABEL_ERRORS[400] = OpenApiResponse(
    response={"oneOf": [{"type": "object", "additionalProperties": True},
                        {"type": "array", "items": {"type": "string"}}]},
    description="DRF field/module validation errors or non-field validation messages.",
)


class LabelCommandListView(generics.ListAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = LabelCommandSerializer

    def batch(self):
        batch = get_object_or_404(scoped_batches(self.request.user), pk=self.kwargs["pk"])
        authorize_staff(self.request.user, batch.makerspace_id)
        self.check_object_permissions(self.request, batch)
        return batch

    def get_queryset(self):
        batch = self.batch()
        return rbac.scope_by_action(self.request.user, rbac.Action.MANAGE_QR,
            LabelPrintCommand.objects.all()).filter(batch=batch).select_related("command")

    @extend_schema(tags=["Devices"], summary="List label commands for a QR batch",
                   responses={200: LabelCommandSerializer(many=True), **LABEL_ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(tags=["Devices"], summary="Send or reprint a QR batch",
                   request=LabelCreateSerializer,
                   responses={200: LabelCommandSerializer, 201: LabelCommandSerializer, **LABEL_ERRORS})
    def post(self, request, pk):
        batch = self.batch()
        serializer = LabelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        label, created = create_label_command(request.user, batch.pk, **serializer.validated_data)
        return Response(LabelCommandSerializer(label).data, status=201 if created else 200)


class SignedLabelView(APIView):
    authentication_classes = [DeviceAuthentication]
    permission_classes = [DeviceRoutePermission]


class LabelContentView(SignedLabelView):
    @extend_schema(tags=["Device protocol"], summary="Download acknowledged label ZIP",
                   responses={(200, "application/zip"): OpenApiResponse(OpenApiTypes.BINARY), **LABEL_ERRORS})
    def get(self, request, pk):
        content, filename = command_content(request.user, pk)
        response = HttpResponse(content, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response


class LabelResultView(SignedLabelView):
    @extend_schema(tags=["Device protocol"], summary="Report an idempotent label result",
                   request=LabelResultSerializer, responses={200: LabelReceiptSerializer, **LABEL_ERRORS})
    def post(self, request, pk):
        serializer = LabelResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = report_result(request.user, pk, **serializer.validated_data)
        return Response(LabelReceiptSerializer(receipt).data)
