from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import ValidationError as SerializerValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff, IsActiveSuperAdmin
from apps.makerspaces.space_pack_export import export_pack
from apps.makerspaces.space_pack_services import (
    apply_pack, authorized_space, preview_pack, save_profile,
)
from .serializers_space_packs import (
    PackErrorSerializer, PackImportSerializer, PackPreviewSerializer,
    PackProfileSerializer, SpacePackSerializer,
)

ERRORS = {code: PackErrorSerializer for code in (400, 401, 403, 404, 409, 423, 503)}


class PackExceptionMixin:
    def handle_exception(self, exc):
        if isinstance(exc, SerializerValidationError):
            return Response({"code": "invalid_pack_configuration", "detail": "Check the pack configuration.",
                             "fields": exc.detail}, status=400)
        if isinstance(exc, DjangoValidationError):
            return Response({"code": "invalid_pack_configuration", "detail": "Check the pack configuration.",
                             "fields": exc.message_dict if hasattr(exc, "message_dict") else exc.messages}, status=400)
        return super().handle_exception(exc)


class SpacePackView(PackExceptionMixin, APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin makerspaces"], summary="Export configuration-only space pack",
                   responses={200: SpacePackSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = authorized_space(request.user, makerspace_id)
        return Response(export_pack(request.user, makerspace))

    @extend_schema(tags=["Admin makerspaces"], summary="Preview or atomically apply a space pack",
                   description="Dry-run defaults true. Apply needs base_checksum from preview. Modules remain superadmin-only. Unrelated entries are retained.",
                   request=PackImportSerializer, responses={200: PackPreviewSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        makerspace = authorized_space(request.user, makerspace_id)
        serializer = PackImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if values["dry_run"]:
            result = preview_pack(request.user, makerspace, values["pack"])
        else:
            result = apply_pack(request.user, makerspace, values["pack"],
                                base_checksum=values.get("base_checksum"))
        return Response(result)


@extend_schema_view(
    get=extend_schema(tags=["Platform"], responses={200: PackProfileSerializer(many=True), **ERRORS}),
    post=extend_schema(tags=["Platform"], request=PackProfileSerializer,
                       responses={201: PackProfileSerializer, **ERRORS}),
)
class SpacePackProfileListView(PackExceptionMixin, generics.ListCreateAPIView):
    permission_classes = [IsActiveSuperAdmin]
    serializer_class = PackProfileSerializer

    def get_queryset(self):
        from apps.makerspaces.models import SpacePackProfile
        return SpacePackProfile.objects.order_by("name", "pk")

    def perform_create(self, serializer):
        serializer.instance = save_profile(self.request.user, **serializer.validated_data)
