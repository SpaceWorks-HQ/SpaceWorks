from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.makerspaces.domain_verification import expected_record, verify_domain
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


class DomainVerificationRecordSerializer(serializers.Serializer):
    host = serializers.CharField()
    type = serializers.CharField()
    value = serializers.CharField()


class DomainVerificationResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Makerspace.DomainStatus.choices)
    token = serializers.CharField()
    expected_record = DomainVerificationRecordSerializer(allow_null=True)
    verified_at = serializers.DateTimeField(allow_null=True)
    detail = serializers.CharField()


@extend_schema(
    tags=["Admin makerspaces"],
    summary="Verify a makerspace custom domain",
    request=None,
    responses={
        200: DomainVerificationResponseSerializer,
        403: OpenApiResponse(description="Missing makerspace management permission."),
        404: OpenApiResponse(description="Makerspace not found."),
    },
)
class MakerspaceVerifyDomainView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = get_object_or_404(
            rbac.scope_by_makerspace(
                request.user,
                servable_queryset(),
                makerspace_field="id",
            ),
            pk=makerspace_id,
        )
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        status, verified_at, detail = verify_domain(makerspace)
        audit.record(
            request.user,
            "makerspace.domain_verify_attempt",
            makerspace=makerspace,
            target=makerspace,
            meta={"domain": makerspace.frontend_domain, "status": status},
        )
        return Response(
            DomainVerificationResponseSerializer(
                {
                    "status": status,
                    "token": makerspace.domain_verification_token,
                    "expected_record": expected_record(makerspace),
                    "verified_at": verified_at,
                    "detail": detail,
                }
            ).data
        )
