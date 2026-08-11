from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.makerspaces import archive_requests
from apps.makerspaces.models import Makerspace, MakerspaceArchiveRequest


class MakerspaceArchiveRequestSerializer(serializers.ModelSerializer):
    requested_by_username = serializers.CharField(
        source="requested_by.username",
        read_only=True,
        default=None,
        allow_null=True,
    )
    resolved_by_username = serializers.CharField(
        source="resolved_by.username",
        read_only=True,
        default=None,
        allow_null=True,
    )

    class Meta:
        model = MakerspaceArchiveRequest
        fields = [
            "id",
            "makerspace",
            "requested_by",
            "requested_by_username",
            "requested_at",
            "resolved_by",
            "resolved_by_username",
            "resolved_at",
            "reason",
            "resolution_note",
            "status",
        ]
        read_only_fields = [
            "id",
            "makerspace",
            "requested_by",
            "requested_by_username",
            "requested_at",
            "resolved_by",
            "resolved_by_username",
            "resolved_at",
            "resolution_note",
            "status",
        ]
        extra_kwargs = {
            "reason": {
                "help_text": "Do not include personal data. Maximum 2,000 characters."
            }
        }

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Explain why this makerspace should be archived.")
        return value


class ArchiveRequestErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField(required=False)


class ArchiveRequestValidationErrorSerializer(serializers.Serializer):
    """DRF field-keyed errors, which are NOT the `detail`/`code` shape.

    A blank or overlong reason fails in `serializer.is_valid(raise_exception=True)` and comes
    back as `{"reason": ["..."]}`. Declaring every 400 as `ArchiveRequestError` published a
    contract the endpoint does not honour, so a generated client would destructure `detail`
    and find nothing. Follows the `ProvisionSubdomainValidationErrorSerializer` precedent.
    """

    reason = serializers.ListField(child=serializers.CharField(), required=False)


class MakerspaceArchiveRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = MakerspaceArchiveRequestSerializer
    pagination_class = None

    def _makerspace(self):
        makerspace = get_object_or_404(
            Makerspace.objects.filter(archived_at__isnull=True),
            pk=self.kwargs["makerspace_id"],
        )
        # Action-based, NOT `is_space_manager_identity`. That helper documents itself as
        # deliberately not inferring identity from actions, so it refuses a custom role
        # granted MANAGE_MAKERSPACE -- which is exactly the Part L custom-role architecture
        # this project runs on. Authority here is the action, not a built-in role name.
        if not rbac.can(self.request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk):
            raise PermissionDenied("Managing archive requests requires MANAGE_MAKERSPACE.")
        return makerspace

    def get_queryset(self):
        makerspace = self._makerspace()
        return MakerspaceArchiveRequest.objects.filter(makerspace=makerspace).select_related(
            "requested_by", "resolved_by"
        )

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="List archive requests for a makerspace",
        responses={
            200: MakerspaceArchiveRequestSerializer(many=True),
            403: OpenApiResponse(response=ArchiveRequestErrorSerializer),
            404: OpenApiResponse(response=ArchiveRequestErrorSerializer),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Request makerspace archival",
        request=MakerspaceArchiveRequestSerializer,
        responses={
            201: MakerspaceArchiveRequestSerializer,
            400: OpenApiResponse(
                response=ArchiveRequestValidationErrorSerializer,
                description="The reason was blank or too long.",
            ),
            403: OpenApiResponse(response=ArchiveRequestErrorSerializer),
            404: OpenApiResponse(response=ArchiveRequestErrorSerializer),
            409: OpenApiResponse(response=ArchiveRequestErrorSerializer),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = archive_requests.create(
            self._makerspace(),
            request.user,
            serializer.validated_data["reason"],
        )
        return Response(
            self.get_serializer(created).data,
            status=status.HTTP_201_CREATED,
        )


class MakerspaceArchiveRequestWithdrawView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin makerspaces"],
        summary="Withdraw a pending makerspace archive request",
        request=None,
        responses={
            200: MakerspaceArchiveRequestSerializer,
            403: OpenApiResponse(response=ArchiveRequestErrorSerializer),
            404: OpenApiResponse(response=ArchiveRequestErrorSerializer),
            409: OpenApiResponse(response=ArchiveRequestErrorSerializer),
        },
    )
    def post(self, request, makerspace_id, pk, *args, **kwargs):
        makerspace = get_object_or_404(
            Makerspace.objects.filter(archived_at__isnull=True),
            pk=makerspace_id,
        )
        # Same action-based gate as the list/create view above.
        if not rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk):
            raise PermissionDenied("Managing archive requests requires MANAGE_MAKERSPACE.")
        archive_request = get_object_or_404(
            MakerspaceArchiveRequest,
            pk=pk,
            makerspace=makerspace,
        )
        withdrawn = archive_requests.withdraw(archive_request, request.user)
        return Response(MakerspaceArchiveRequestSerializer(withdrawn).data)
