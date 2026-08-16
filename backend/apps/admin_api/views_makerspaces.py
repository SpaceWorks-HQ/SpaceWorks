from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.admin_api.serializers_inventory import (
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)
from apps.admin_api.serializers_makerspaces import (
    MakerspaceSerializer,
    MakerspaceSwitcherSerializer,
    ReturnPolicySerializer,
)
from apps.audit import services as audit
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from apps.makerspaces.limits import add_storage
from apps.makerspaces.models import Makerspace
from apps.makerspaces.origin_scope import origin_scoped_makerspace_id
from apps.makerspaces.servability import servable_queryset


@extend_schema(tags=["Admin makerspaces"], summary="List or create makerspaces")
class MakerspaceListCreateView(generics.ListCreateAPIView):
    serializer_class = MakerspaceSerializer
    permission_classes = [IsActiveStaff]
    pagination_class = None

    def get_queryset(self):
        # The staff console switcher must list a makerspace for any staff role
        # that has a surface there — including print managers, who hold only
        # MANAGE_PRINTING (no VIEW_INVENTORY). Scope by the union so a pure print
        # manager isn't stuck on an empty list / "No makerspace" screen. Create
        # (POST) stays superadmin-only in perform_create, so widening the read
        # scope here doesn't grant anyone new write access.
        queryset = servable_queryset()
        actor = self.request.user
        origin_scope = origin_scoped_makerspace_id(self.request)
        scope = rbac.makerspaces_for_actions(
            actor,
            *sorted(rbac.ROLE_GRANTABLE_ACTIONS),
        )
        if not scope:
            return queryset.none()
        if scope is not rbac.ALL:
            queryset = queryset.filter(id__in=scope)
        if origin_scope is not None:
            queryset = queryset.filter(id=origin_scope)
        return queryset.order_by("name")

    def list(self, request, *args, **kwargs):
        # Serialize PER ROW: the full makerspace config (public_api_key, CORS
        # origins, SMTP host/username, module/theme config) is only for rows the
        # user can VIEW_INVENTORY. Rows reachable solely via MANAGE_PRINTING (a
        # print manager populating the switcher) get the slim serializer. A
        # mixed-role user (VIEW_INVENTORY in A, print-only in B) therefore sees A
        # in full and B slim — choosing one serializer for the whole list would
        # leak B's config. Settings writes stay MANAGE_MAKERSPACE-gated elsewhere.
        view_scope = rbac.makerspaces_for_action(request.user, rbac.Action.VIEW_INVENTORY)
        context = self.get_serializer_context()

        def serialize(makerspace):
            can_view = view_scope is rbac.ALL or makerspace.id in view_scope
            serializer = MakerspaceSerializer if can_view else MakerspaceSwitcherSerializer
            return serializer(makerspace, context=context).data

        return Response([serialize(item) for item in self.filter_queryset(self.get_queryset())])

    def perform_create(self, serializer):
        if not (self.request.user.is_superuser or self.request.user.role == User.Role.SUPERADMIN):
            raise PermissionDenied()
        instance = serializer.save(created_by=self.request.user)
        audit.record(
            self.request.user,
            "makerspace.created",
            makerspace=instance,
            target=instance,
        )


@extend_schema(tags=["Admin makerspaces"], summary="Retrieve or update a makerspace")
class MakerspaceDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = MakerspaceSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        return MakerspaceSerializer

    def get_queryset(self):
        actor = self.request.user
        queryset = servable_queryset()
        action = (
            rbac.Action.MANAGE_MAKERSPACE
            if self.request.method == "PATCH"
            else rbac.Action.VIEW_INVENTORY
        )
        return rbac.scope_by_action(self.request.user, action, queryset, field="id")

    def get_object(self):
        self._makerspace_object = super().get_object()
        return self._makerspace_object

    def perform_update(self, serializer):
        was_enabled = serializer.instance.superadmin_access_enabled
        previous_features = list(serializer.instance.enabled_features)
        previous_geofence = {"enabled": serializer.instance.geofence_enabled, "configured": serializer.instance.geofence_effective, "radius_m": serializer.instance.geofence_radius_m, "latitude": str(serializer.instance.geofence_latitude), "longitude": str(serializer.instance.geofence_longitude)}
        instance = serializer.save()
        audit.record(
            self.request.user,
            "makerspace.updated",
            makerspace=instance,
            target=instance,
        )
        if previous_features != instance.enabled_features:
            audit.record(
                self.request.user,
                "makerspace.features_changed",
                makerspace=instance,
                target=instance,
                meta={"before": previous_features, "after": instance.enabled_features},
            )
        if was_enabled != instance.superadmin_access_enabled:
            audit.record(
                self.request.user,
                "makerspace.superadmin_access_changed",
                makerspace=instance,
                target=instance,
                meta={"enabled": instance.superadmin_access_enabled},
            )


        current_geofence = {"enabled": instance.geofence_enabled, "configured": instance.geofence_effective, "radius_m": instance.geofence_radius_m, "latitude": str(instance.geofence_latitude), "longitude": str(instance.geofence_longitude)}
        if previous_geofence != current_geofence:
            audit.record(self.request.user, "makerspace.geofence_updated", makerspace=instance, target=instance, meta=current_geofence)
@extend_schema(tags=["Admin makerspaces"], summary="Retrieve or update return policy")
class ReturnPolicyView(generics.RetrieveUpdateAPIView):
    serializer_class = ReturnPolicySerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        makerspace_id = self.kwargs["makerspace_id"]
        return get_object_or_404(
            rbac.scope_by_action(
                self.request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                Makerspace.objects.all(),
                field="id",
            ),
            pk=makerspace_id,
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request.user,
            "makerspace.return_policy_updated",
            makerspace=instance,
            target=instance,
            meta={"default_loan_days": instance.default_loan_days},
        )


class MakerspaceImageView(APIView):
    permission_classes = [IsActiveStaff]
    image_field = ""
    attach_action = ""
    clear_action = ""

    def _makerspace(self, request, makerspace_id):
        makerspace = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        return makerspace

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Create a makerspace public image upload URL",
        request=PublicImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        serializer = PublicImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type,
            serializer.validated_data["filename"],
        )
        object_key = public_image_storage.build_object_key("makerspace", makerspace.id, ext)
        try:
            upload = public_image_storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            PublicImageUploadResponseSerializer({"object_key": object_key, **upload}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Attach an uploaded public image to a makerspace",
        request=PublicImageAttachRequestSerializer,
        responses={
            200: MakerspaceSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    @transaction.atomic
    def put(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        serializer = PublicImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        expected_prefix = f"makerspace/{makerspace.id}/"
        if not object_key.startswith(expected_prefix):
            raise ValidationError({"object_key": "Image object key is outside this makerspace."})
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if object_key and public_image_storage.public_image_key_in_use(
            makerspace.id,
            object_key,
            makerspace_field=self.image_field,
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        try:
            result = public_image_storage.finalize_upload(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if result.status != "ok":
            if result.status in {"empty", "too_large"}:
                public_image_storage.delete_object(object_key)
                public_image_storage.delete_object(
                    public_image_storage.staging_key(object_key)
                )
            raise ValidationError(
                {"object_key": public_image_storage.finalize_error_message(result)}
            )
        try:
            is_valid_image = public_image_storage.sniff_is_valid_image(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if not is_valid_image:
            public_image_storage.delete_object(object_key)
            public_image_storage.delete_object(public_image_storage.staging_key(object_key))
            raise ValidationError(
                {"object_key": "Uploaded file is not a valid image."}
            )
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if object_key and public_image_storage.public_image_key_in_use(
            makerspace.id,
            object_key,
            makerspace_field=self.image_field,
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        old_key = getattr(makerspace, self.image_field)
        if object_key != old_key:
            add_storage(makerspace, result.size)
        if old_key and old_key != object_key:
            public_image_storage.release_public_image_on_commit(makerspace, old_key)
        setattr(makerspace, self.image_field, object_key)
        makerspace.save(update_fields=[self.image_field, "updated_at"])
        audit.record(
            request.user,
            self.attach_action,
            makerspace=makerspace,
            target=makerspace,
        )
        return Response(MakerspaceSerializer(makerspace, context={"request": request}).data)

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Clear a makerspace public image",
        responses={200: MakerspaceSerializer},
    )
    @transaction.atomic
    def delete(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        old_key = getattr(makerspace, self.image_field)
        if old_key:
            public_image_storage.release_public_image_on_commit(makerspace, old_key)
        setattr(makerspace, self.image_field, "")
        makerspace.save(update_fields=[self.image_field, "updated_at"])
        audit.record(
            request.user,
            self.clear_action,
            makerspace=makerspace,
            target=makerspace,
        )
        return Response(MakerspaceSerializer(makerspace, context={"request": request}).data)


class MakerspaceLogoImageView(MakerspaceImageView):
    image_field = "logo_key"
    attach_action = "makerspace.logo_attached"
    clear_action = "makerspace.logo_cleared"


class MakerspaceCoverImageView(MakerspaceImageView):
    image_field = "cover_image_key"
    attach_action = "makerspace.cover_attached"
    clear_action = "makerspace.cover_cleared"
