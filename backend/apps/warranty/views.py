from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.warranty.serializers import WarrantySerializer, WarrantyUpsertSerializer
from apps.warranty.views_report import MakerspaceWarrantyReportView
from apps.warranty.access import (
    resolve_asset_host,
    resolve_machine_host,
)
from apps.audit import services as audit
from apps.makerspaces.guards import require_module
from apps.machines import access as machine_access
from apps.warranty.models import Warranty


ERRORS = {401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


class AssetWarrantyView(APIView):
    permission_classes = [IsActiveStaff]

    def _asset(self, request, pk):
        asset = resolve_asset_host(request.user, pk)
        require_action(request.user, rbac.Action.EDIT_INVENTORY, asset.makerspace_id)
        require_module(asset.makerspace_id, "staff_admin")
        return asset

    @extend_schema(
        tags=["Admin warranty"],
        summary="Retrieve warranty details for an inventory asset",
        responses={200: WarrantySerializer, **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        asset = self._asset(request, pk)
        warranty = _asset_warranty(asset)
        if warranty is None:
            return Response(None)
        return Response(WarrantySerializer(warranty).data)

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create or update warranty details for an inventory asset",
        request=WarrantyUpsertSerializer,
        responses={
            200: WarrantySerializer,
            400: OpenApiResponse(description="Invalid warranty details."),
            **ERRORS,
        },
    )
    def put(self, request, pk, *args, **kwargs):
        asset = self._asset(request, pk)
        serializer = WarrantyUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        warranty, created = _upsert_warranty(
            asset=asset,
            data=serializer.validated_data,
        )
        audit.record(
            request.user,
            "warranty.created" if created else "warranty.updated",
            makerspace=asset.makerspace,
            target=warranty,
        )
        return Response(WarrantySerializer(_reload_warranty(warranty)).data)


class MachineWarrantyView(APIView):
    permission_classes = [IsActiveStaff]

    def _machine(self, request, pk):
        machine = resolve_machine_host(request.user, pk)
        if not machine_access.can_manage_machine(request.user, machine):
            raise PermissionDenied()
        require_module(machine.makerspace_id, "machines")
        return machine

    @extend_schema(
        tags=["Admin warranty"],
        summary="Retrieve warranty details for a machine",
        responses={200: WarrantySerializer, **ERRORS},
    )
    def get(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        warranty = _machine_warranty(machine)
        if warranty is None:
            return Response(None)
        return Response(WarrantySerializer(warranty).data)

    @extend_schema(
        tags=["Admin warranty"],
        summary="Create or update warranty details for a machine",
        request=WarrantyUpsertSerializer,
        responses={
            200: WarrantySerializer,
            400: OpenApiResponse(description="Invalid warranty details."),
            **ERRORS,
        },
    )
    def put(self, request, pk, *args, **kwargs):
        machine = self._machine(request, pk)
        serializer = WarrantyUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        warranty, created = _upsert_warranty(
            machine=machine,
            data=serializer.validated_data,
        )
        audit.record(
            request.user,
            "warranty.created" if created else "warranty.updated",
            makerspace=machine.makerspace,
            target=warranty,
        )
        return Response(WarrantySerializer(_reload_warranty(warranty)).data)


def _asset_warranty(asset):
    return _host_warranty("asset", asset)



def _machine_warranty(machine):
    return _host_warranty("machine", machine)


def _host_warranty(host_kind, host):
    return (
        Warranty.objects.select_related("asset", "machine")
        .prefetch_related("documents")
        .filter(**{host_kind: host})
        .first()
    )


def _reload_warranty(warranty):
    return (
        Warranty.objects.select_related("asset", "machine")
        .prefetch_related("documents")
        .get(pk=warranty.pk)
    )


@transaction.atomic
def _upsert_warranty(*, data, asset=None, machine=None):
    hosts = {
        kind: host
        for kind, host in (("asset", asset), ("machine", machine))
        if host is not None
    }
    if len(hosts) != 1:
        raise ValueError("Exactly one warranty host is required.")
    host_kind, host = next(iter(hosts.items()))
    warranty, created = Warranty.objects.get_or_create(
        **{host_kind: host},
        defaults={"makerspace_id": host.makerspace_id},
    )
    warranty.makerspace_id = host.makerspace_id
    for field in ("purchased_on", "warranty_expires_on", "vendor_name", "vendor_contact"):
        if field in data:
            setattr(warranty, field, data[field])
    try:
        warranty.full_clean()
    except DjangoValidationError as exc:
        raise ValidationError(getattr(exc, "message_dict", exc.messages)) from exc
    warranty.save()
    return warranty, created

__all__ = [
    "AssetWarrantyView",
    "MachineWarrantyView",
    "MakerspaceWarrantyReportView",
]
