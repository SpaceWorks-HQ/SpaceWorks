from django.shortcuts import get_object_or_404
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api import settings_audit
from apps.admin_api.serializers_makerspaces import (
    MakerspaceSerializer,
    MakerspaceSwitcherSerializer,
    ReturnPolicySerializer,
)
from apps.admin_api.views_makerspace_images import (
    MakerspaceCoverImageView,
    MakerspaceLogoImageView,
)
from apps.audit import services as audit
from apps.makerspaces.domain_audit import record_domain_change
from apps.makerspaces.models import Makerspace
from apps.makerspaces.origin_scope import origin_scoped_makerspace_id
from apps.makerspaces.servability import servable_queryset


_INVALID = OpenApiResponse(description="Field validation errors, keyed by field.")
_NOT_FOUND = OpenApiResponse(
    description=(
        "Makerspace not found, archived, not active, hidden from superadmins, or outside "
        "the actor's scope for this method."
    )
)


@extend_schema_view(
    get=extend_schema(
        tags=["Admin makerspaces"],
        summary="List makerspaces the actor has a staff surface in",
        responses={
            200: MakerspaceSerializer(many=True),
            403: OpenApiResponse(description="Not an active staff account."),
        },
    ),
    post=extend_schema(
        tags=["Admin makerspaces"],
        summary="Create a makerspace (superadmin only)",
        responses={
            201: MakerspaceSerializer,
            400: _INVALID,
            403: OpenApiResponse(description="Only a superadmin can create a makerspace."),
        },
    ),
)
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
        queryset = servable_queryset().select_related("archive_custody_state")
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
        view_scope = rbac.makerspaces_for_action(
            request.user, rbac.Action.VIEW_INVENTORY
        )
        context = self.get_serializer_context()

        def serialize(makerspace):
            can_view = view_scope is rbac.ALL or makerspace.id in view_scope
            serializer = (
                MakerspaceSerializer if can_view else MakerspaceSwitcherSerializer
            )
            return serializer(makerspace, context=context).data

        return Response([serialize(item) for item in self.filter_queryset(self.get_queryset())])

    def perform_create(self, serializer):
        if not (
            self.request.user.is_superuser
            or self.request.user.role == User.Role.SUPERADMIN
        ):
            raise PermissionDenied()
        instance = serializer.save(created_by=self.request.user)
        audit.record(
            self.request.user,
            "makerspace.created",
            makerspace=instance,
            target=instance,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Admin makerspaces"],
        summary="Retrieve a makerspace's settings",
        responses={200: MakerspaceSerializer, 404: _NOT_FOUND},
    ),
    patch=extend_schema(
        tags=["Admin makerspaces"],
        summary="Update a makerspace's settings",
        description=(
            "Needs manage_makerspace. `enabled_modules` is superadmin-owned and edited only "
            "in /control/ or the module console: a body carrying it is refused with 403."
        ),
        responses={
            200: MakerspaceSerializer,
            400: _INVALID,
            403: OpenApiResponse(description="The body carries `enabled_modules`."),
            404: _NOT_FOUND,
        },
    ),
)
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
        # Feature OFF must serialize with services that re-check the same row under
        # lock. Otherwise a station sync can pass its gate while this PATCH commits OFF.
        with transaction.atomic():
            serializer.instance = Makerspace.objects.select_for_update().get(
                pk=serializer.instance.pk
            )
            requested = set(serializer.validated_data)
            before = settings_audit.snapshot(serializer.instance, requested)
            previous_features = list(serializer.instance.enabled_features)
            previous_domain = serializer.instance.frontend_domain
            previous_geofence = {
                "enabled": serializer.instance.geofence_enabled,
                "configured": serializer.instance.geofence_effective,
                "radius_m": serializer.instance.geofence_radius_m,
                "latitude": str(serializer.instance.geofence_latitude),
                "longitude": str(serializer.instance.geofence_longitude),
            }
            instance = serializer.save()
            audit.record(
                self.request.user,
                "makerspace.updated",
                makerspace=instance,
                target=instance,
                meta={
                    "fields": settings_audit.changed_fields(before, instance, requested)
                },
            )
            if previous_domain != instance.frontend_domain:
                record_domain_change(self.request.user, instance, previous_domain)
            if previous_features != instance.enabled_features:
                audit.record(
                    self.request.user,
                    "makerspace.features_changed",
                    makerspace=instance,
                    target=instance,
                    meta={"before": previous_features, "after": instance.enabled_features},
                )
            current_geofence = {
                "enabled": instance.geofence_enabled,
                "configured": instance.geofence_effective,
                "radius_m": instance.geofence_radius_m,
                "latitude": str(instance.geofence_latitude),
                "longitude": str(instance.geofence_longitude),
            }
            if previous_geofence != current_geofence:
                audit.record(
                    self.request.user,
                    "makerspace.geofence_updated",
                    makerspace=instance,
                    target=instance,
                    meta=current_geofence,
                )


@extend_schema_view(
    get=extend_schema(
        tags=["Admin makerspaces"],
        summary="Retrieve the return policy",
        responses={200: ReturnPolicySerializer, 404: _NOT_FOUND},
    ),
    patch=extend_schema(
        tags=["Admin makerspaces"],
        summary="Update the return policy",
        responses={200: ReturnPolicySerializer, 400: _INVALID, 404: _NOT_FOUND},
    ),
)
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
                servable_queryset(),
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
