"""Paginated staff lists and matching machine-scoped detail/mutation authority."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.devices.models import PrinterDeviceBinding, PrinterJob
from apps.devices.printer_access import authorize_staff, scope_printers
from apps.devices.serializers_printers import (
    BindingCreateSerializer, BindingSerializer, BindingUpdateSerializer,
    JobCreateSerializer, JobSerializer, StrictSerializer,
)
from apps.devices.services_printer_apply import approve_report
from apps.devices.services_printer_bindings import create_binding, delete_binding, update_binding
from apps.devices.services_printer_jobs import create_job
from apps.devices.views_printer_common import PRINTER_ERRORS


def scoped_object(actor, model, pk):
    row = get_object_or_404(scope_printers(actor, model.objects.all()), pk=pk)
    authorize_staff(actor, row.makerspace_id, row.machine)
    return row


class PrinterBindingListView(generics.ListAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = BindingSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        authorize_staff(self.request.user, makerspace_id)
        return scope_printers(self.request.user, PrinterDeviceBinding.objects.all()).filter(makerspace_id=makerspace_id).order_by("created_at", "id")

    @extend_schema(tags=["Devices"], responses={200: BindingSerializer(many=True), **PRINTER_ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(tags=["Devices"], request=BindingCreateSerializer, responses={201: BindingSerializer, **PRINTER_ERRORS})
    def post(self, request, makerspace_id):
        authorize_staff(request.user, makerspace_id)
        serializer = BindingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = create_binding(request.user, makerspace_id, **serializer.validated_data)
        return Response(BindingSerializer(row).data, status=201)


class PrinterBindingDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Devices"], request=BindingUpdateSerializer, responses={200: BindingSerializer, **PRINTER_ERRORS})
    def patch(self, request, pk):
        scoped_object(request.user, PrinterDeviceBinding, pk)
        serializer = BindingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(BindingSerializer(update_binding(request.user, pk, serializer.validated_data)).data)

    @extend_schema(tags=["Devices"], request=None, responses={204: None, **PRINTER_ERRORS})
    def delete(self, request, pk):
        scoped_object(request.user, PrinterDeviceBinding, pk)
        delete_binding(request.user, pk)
        return Response(status=204)


class PrinterJobListView(generics.ListAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = JobSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        authorize_staff(self.request.user, makerspace_id)
        return scope_printers(self.request.user, PrinterJob.objects.all()).filter(makerspace_id=makerspace_id).prefetch_related("consumptions").order_by("-created_at", "id")

    @extend_schema(tags=["Devices"], responses={200: JobSerializer(many=True), **PRINTER_ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(tags=["Devices"], request=JobCreateSerializer, responses={201: JobSerializer, **PRINTER_ERRORS})
    def post(self, request, makerspace_id):
        authorize_staff(request.user, makerspace_id)
        serializer = JobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(JobSerializer(create_job(request.user, makerspace_id, **serializer.validated_data)).data, status=201)


class PrinterJobDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Devices"], responses={200: JobSerializer, **PRINTER_ERRORS})
    def get(self, request, pk):
        return Response(JobSerializer(scoped_object(request.user, PrinterJob, pk)).data)


class PrinterJobApplyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Devices"], request=StrictSerializer, responses={200: JobSerializer, **PRINTER_ERRORS})
    def post(self, request, pk):
        scoped_object(request.user, PrinterJob, pk)
        serializer = StrictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(JobSerializer(approve_report(request.user, pk)).data)
