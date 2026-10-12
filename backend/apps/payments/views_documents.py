"""Authenticated, tenant-scoped document metadata and expiring PDF grants."""

from django.core import signing
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, active_user
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.payments.document_delivery import DOWNLOAD_TTL, SALT, download_path
from apps.payments.member_access import member_may_see_own_charges
from apps.payments.member_scope import member_payment_queryset
from apps.payments.models import PaymentDocument
from apps.makerspaces.origin_scope import object_in_staff_origin_scope


class PaymentDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentDocument
        fields = ("id", "payment", "number", "kind", "issued_at", "money_at", "amount", "currency")


class DocumentPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = PaymentDocumentSerializer(many=True)


class DownloadGrantSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField()


ERRORS = {code: OpenApiResponse(ErrorSerializer) for code in (400, 401, 403, 404)}


def scoped_documents(user, makerspace_id, audience):
    if audience == "staff":
        if not active_user(user):
            raise PermissionDenied("An active staff account is required.")
        return rbac.scope_by_action(user, rbac.Action.VIEW_FINANCE,
                                    PaymentDocument.objects.all(), field="makerspace_id").filter(makerspace_id=makerspace_id)
    if not member_may_see_own_charges(user, makerspace_id):
        raise PermissionDenied("An active membership or an existing charge is required.")
    return PaymentDocument.objects.filter(payment__in=member_payment_queryset(user, makerspace_id))


class MemberDocumentListView(APIView):
    permission_classes = [IsAuthenticated]
    audience = "member"

    @extend_schema(tags=["Payments"], summary="List scoped payment documents", request=None,
                   parameters=[OpenApiParameter("page", int)], responses={200: DocumentPageSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        rows = scoped_documents(request.user, makerspace_id, self.audience).order_by("-issued_at", "-pk")
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(PaymentDocumentSerializer(page, many=True).data)


class StaffDocumentListView(MemberDocumentListView):
    permission_classes = [IsActiveStaff]
    audience = "staff"


class MemberDocumentGrantView(APIView):
    permission_classes = [IsAuthenticated]
    audience = "member"

    @extend_schema(tags=["Payments"], summary="Get a user-bound five-minute PDF download URL",
                   request=None, responses={200: DownloadGrantSerializer, **ERRORS})
    def get(self, request, makerspace_id, document_id):
        document = get_object_or_404(scoped_documents(request.user, makerspace_id, self.audience), pk=document_id)
        return Response({"url": download_path(document, request.user, makerspace_id=makerspace_id,
                                              audience=self.audience), "expires_in": DOWNLOAD_TTL})


class StaffDocumentGrantView(MemberDocumentGrantView):
    permission_classes = [IsActiveStaff]
    audience = "staff"


class DocumentDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Payments"], summary="Download an issued payment document PDF",
                   request=None, parameters=[OpenApiParameter("token", str, required=True)],
                   responses={(200, "application/pdf"): OpenApiTypes.BINARY, **ERRORS})
    def get(self, request, document_id):
        try:
            grant = signing.loads(request.query_params.get("token", ""), salt=SALT, max_age=DOWNLOAD_TTL)
        except signing.BadSignature:
            raise ValidationError({"detail": "Download URL is invalid or expired.", "code": "document_url_expired"})
        if grant["user"] != request.user.pk or grant["document"] != document_id:
            raise PermissionDenied()
        document = get_object_or_404(scoped_documents(request.user, grant["space"], grant["audience"]), pk=document_id)
        if grant["audience"] == "staff" and not object_in_staff_origin_scope(request, document):
            raise PermissionDenied("Document is outside this staff origin's makerspace.")
        from apps.payments.document_pdf import render_document_pdf
        response = HttpResponse(render_document_pdf(document), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="payment-document-{document.pk}.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response
