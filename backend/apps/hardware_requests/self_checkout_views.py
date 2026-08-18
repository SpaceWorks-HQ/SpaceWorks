from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.audit import services as audit
from apps.hardware_requests import self_checkout_workflow
from apps.hardware_requests.self_checkout_serializers import (
    PublicToolCheckoutSerializer,
    PublicToolEvidenceUrlRequestSerializer,
    PublicToolLoanSerializer,
    PublicToolScanSerializer,
)
from apps.hardware_requests.view_helpers import PUBLIC_ERROR_RESPONSES
from apps.evidence.models import EvidencePhoto
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.serializers import EvidenceUrlResponseSerializer
from apps.evidence.storage import StorageUnavailable, evidence_object_key, presigned_upload
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.guards import require_feature
from apps.presence.guard import require_active_member_presence
from apps.openapi import (
    PUBLIC_API_AUTH_PARAMETERS,
    PUBLIC_TOOL_CHECKOUT_EXAMPLE,
    PUBLIC_TOOL_SCAN_EXAMPLE,
)
from rest_framework.exceptions import ValidationError


class PublicToolEvidenceUploadUrlView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_tool_checkout"

    @extend_schema(
        tags=["Public requests"],
        summary="Create a public self-checkout evidence upload URL",
        parameters=PUBLIC_API_AUTH_PARAMETERS,
        request=PublicToolEvidenceUrlRequestSerializer,
        responses={201: EvidenceUrlResponseSerializer, **PUBLIC_ERROR_RESPONSES},
    )
    def post(self, request, makerspace_slug, *args, **kwargs):
        makerspace = get_public_makerspace(makerspace_slug)
        require_feature(makerspace, "inventory.self_checkout")
        require_active_member_presence(request.user, makerspace)
        serializer = PublicToolEvidenceUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["content_type"] not in settings.EVIDENCE_ALLOWED_MIME:
            raise ValidationError({"content_type": "Unsupported evidence content type."})
        object_key = evidence_object_key(makerspace.id, data["evidence_type"])
        try:
            upload = presigned_upload(object_key, data["content_type"])
        except StorageUnavailable:
            return storage_unavailable_response()
        photo = EvidencePhoto.objects.create(
            makerspace=makerspace,
            evidence_type=data["evidence_type"],
            object_key=object_key,
            content_type=data["content_type"],
            size_bytes=data.get("size_bytes"),
            uploaded_by=request.user,
        )
        audit.record(
            request.user,
            "evidence.upload_url_issued",
            makerspace=makerspace,
            target=photo,
            meta={"surface": "public_self_checkout", "type": data["evidence_type"]},
        )
        response = {
            "evidence_id": photo.pk,
            "upload_url": upload["url"],
            "fields": upload.get("fields", {}),
            "object_key": object_key,
        }
        if upload.get("method"):
            response["method"] = upload["method"]
            response["headers"] = upload.get("headers", {})
        return Response(EvidenceUrlResponseSerializer(response).data, status=status.HTTP_201_CREATED)


class PublicToolCheckoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_tool_checkout"

    @extend_schema(
        tags=["Public requests"],
        summary="Check out a public tool by QR",
        parameters=PUBLIC_API_AUTH_PARAMETERS,
        request=PublicToolCheckoutSerializer,
        responses={201: PublicToolLoanSerializer, **PUBLIC_ERROR_RESPONSES},
        examples=[PUBLIC_TOOL_CHECKOUT_EXAMPLE],
    )
    def post(self, request, makerspace_slug, *args, **kwargs):
        makerspace = get_public_makerspace(makerspace_slug)
        require_feature(makerspace, "inventory.self_checkout")
        require_active_member_presence(request.user, makerspace)
        serializer = PublicToolCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = self_checkout_workflow.checkout_tool(
            makerspace,
            request.user,
            serializer.validated_data["payload"],
            evidence_id=serializer.validated_data["evidence_id"],
            remark=serializer.validated_data.get("remark", ""),
        )
        return Response(PublicToolLoanSerializer(loan).data, status=status.HTTP_201_CREATED)


class PublicToolReturnView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_tool_return"

    @extend_schema(
        tags=["Public requests"],
        summary="Return a public tool by QR",
        parameters=PUBLIC_API_AUTH_PARAMETERS,
        request=PublicToolScanSerializer,
        responses={200: PublicToolLoanSerializer, **PUBLIC_ERROR_RESPONSES},
        examples=[PUBLIC_TOOL_SCAN_EXAMPLE],
    )
    def post(self, request, makerspace_slug, *args, **kwargs):
        makerspace = get_public_makerspace(makerspace_slug)
        require_feature(makerspace, "inventory.self_checkout")
        require_active_member_presence(request.user, makerspace)
        serializer = PublicToolScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loan = self_checkout_workflow.return_tool(
            makerspace,
            request.user,
            serializer.validated_data["payload"],
            evidence_id=serializer.validated_data["evidence_id"],
            remark=serializer.validated_data["remark"],
            report_problem=serializer.validated_data["report_problem"],
            problem_note=serializer.validated_data["problem_note"],
        )
        return Response(PublicToolLoanSerializer(loan).data)


def _require_module(makerspace, module_key):
    if not module_enabled(makerspace, module_key):
        raise ValidationError({"module": f"{module_key} is disabled for this makerspace."})
