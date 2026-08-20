from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.api_client_serializers import ApiKeyRequestSerializer
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.apiclients.models import ApiKeyRequest
from apps.audit import services as audit
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.servability import is_servable


@extend_schema(
    tags=["API key requests"],
    summary="List or create API key requests",
    parameters=[OpenApiParameter("makerspace", int, OpenApiParameter.QUERY)],
)
class ApiKeyRequestListCreateView(generics.ListCreateAPIView):
    serializer_class = ApiKeyRequestSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        queryset = (
            ApiKeyRequest.objects.select_related("makerspace", "requester")
            .filter(requester=self.request.user)
            .order_by("-created_at")
        )
        makerspace_id = self.request.query_params.get("makerspace")
        if makerspace_id:
            queryset = queryset.filter(makerspace_id=makerspace_id)
        return queryset

    def perform_create(self, serializer):
        makerspace = serializer.validated_data["makerspace"]
        # Any active staff member may file a request. Issuance remains restricted
        # to the superadmin control plane, so this gate checks membership only.
        user = self.request.user
        is_superadmin = user.is_superuser or user.role == User.Role.SUPERADMIN
        is_member = MakerspaceMembership.objects.filter(
            user=user, makerspace_id=makerspace.id, status="active"
        ).exists()
        if not is_servable(makerspace):
            raise PermissionDenied()
        if is_superadmin and not is_member:
            require_action(user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        elif not is_member:
            raise PermissionDenied()

        api_key_request = serializer.save(
            requester=user,
            status=ApiKeyRequest.Status.PENDING,
        )
        audit.record(
            user,
            "api_key_request.created",
            makerspace=makerspace,
            target=api_key_request,
            meta={"allowed_origins": api_key_request.allowed_origins},
        )
