from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics

from apps.accounts import rbac
from apps.admin_api import settings_audit
from apps.admin_api.api_client_serializers import ApiIntegrationSettingsSerializer
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.makerspaces.servability import servable_queryset

_NOT_FOUND = OpenApiResponse(
    description="Makerspace not found, archived, not active, or outside the actor's scope."
)
_FORBIDDEN = OpenApiResponse(description="The actor lacks manage_makerspace here.")


@extend_schema_view(
    get=extend_schema(
        tags=["API clients"],
        summary="Retrieve API integration settings",
        responses={200: ApiIntegrationSettingsSerializer, 401: OpenApiResponse(description="Authentication required."), 403: _FORBIDDEN, 404: _NOT_FOUND},
    ),
    patch=extend_schema(
        tags=["API clients"],
        summary="Update API integration settings",
        responses={
            200: ApiIntegrationSettingsSerializer,
            400: OpenApiResponse(description="Field validation errors, keyed by field."),
            401: OpenApiResponse(description="Authentication required."),
            403: _FORBIDDEN,
            404: _NOT_FOUND,
        },
    ),
)
class ApiIntegrationSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = ApiIntegrationSettingsSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        # 404 before 403, like every sibling makerspace route: a tenant the actor cannot
        # see -- another makerspace, an archived or importing one -- must not be
        # confirmed by a 403, and only a visible actor lacking the action gets 403.
        makerspace = get_object_or_404(
            rbac.scope_by_visibility_or_action(
                self.request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=self.kwargs["makerspace_id"],
        )
        require_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        return makerspace

    def perform_update(self, serializer):
        requested = set(serializer.validated_data)
        before = settings_audit.snapshot(serializer.instance, requested)
        instance = serializer.save()
        audit.record(
            self.request.user,
            "api_integration.updated",
            makerspace=instance,
            target=instance,
            meta={"fields": settings_audit.changed_fields(before, instance, requested)},
        )
