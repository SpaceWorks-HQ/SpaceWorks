"""Staff API for asynchronous, tenant-scoped audit verification runs.

POST always answers 202 (new or deduplicated run) or a bounded refusal; the work runs in
Celery. Every route resolves the makerspace through ``scope_by_action(VIEW_AUDIT)`` with
archived and superadmin-hidden spaces excluded, so an out-of-scope space is a 404, never
a hint that it exists.
"""

from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import verification_runs as runs
from apps.audit.models import AuditVerificationRun
from apps.audit.serializers_verification import (
    VerificationAcceptedSerializer,
    VerificationRequestSerializer,
    VerificationRunSerializer,
    run_payload,
    status_url,
)
from apps.makerspaces.models import Makerspace

ERROR_BODY = inline_serializer(
    "AuditVerificationError", {"code": serializers.CharField(), "detail": serializers.CharField()}
)
ERRORS = {
    400: OpenApiResponse(ERROR_BODY, description="Invalid filters, `narrow_audit_range` or "
                         "`audit_verification_scope_too_large`."),
    401: OpenApiResponse(description="Not authenticated."),
    403: OpenApiResponse(description="Not active staff."),
    404: OpenApiResponse(description="Makerspace or run not in the caller's VIEW_AUDIT scope."),
}


class VerificationPagination(PageNumberPagination):
    page_size = 24


def _scoped_makerspace(user, makerspace_id):
    spaces = rbac.scope_by_action(
        user, rbac.Action.VIEW_AUDIT, Makerspace.objects.all(), field="id"
    )
    spaces = rbac.hide_from_superadmin(user, spaces, field="id")
    archived = rbac.archived_makerspace_ids()
    if archived:
        spaces = spaces.exclude(id__in=archived)
    makerspace = spaces.filter(pk=makerspace_id).first()
    if makerspace is None:
        raise Http404
    return makerspace


def _payload(request, run):
    event = runs.latest_event(run)
    return run_payload(run, event, superuser=bool(request.user.is_superuser))


class AuditVerificationListCreateView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_scope = "audit_verification"

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    @extend_schema(
        tags=["Audit verification"],
        summary="List audit verification runs for one makerspace",
        responses={200: VerificationRunSerializer(many=True), **ERRORS},
    )
    def get(self, request, makerspace_id):
        makerspace = _scoped_makerspace(request.user, makerspace_id)
        paginator = VerificationPagination()
        page = paginator.paginate_queryset(
            AuditVerificationRun.objects.filter(makerspace=makerspace).order_by("-pk"),
            request,
            view=self,
        )
        return paginator.get_paginated_response([_payload(request, run) for run in page])

    @extend_schema(
        tags=["Audit verification"],
        summary="Request asynchronous verification of the filtered audit rows",
        description=(
            "Always asynchronous: 202 with the new or deduplicated run (`deduplicated`), "
            "then poll `status_url`. One active run per makerspace (409 "
            "`audit_verification_busy`); at most 10,000 selected rows and bounded expanded "
            "work (400); throttled per user (429)."
        ),
        request=VerificationRequestSerializer,
        responses={
            202: VerificationAcceptedSerializer,
            409: OpenApiResponse(ERROR_BODY, description="`audit_verification_busy`."),
            429: OpenApiResponse(description="Throttled."),
            **ERRORS,
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _scoped_makerspace(request.user, makerspace_id)
        filters = VerificationRequestSerializer(data=request.data)
        filters.is_valid(raise_exception=True)
        try:
            run, deduplicated = runs.request_run(
                request.user, makerspace.pk, filters.validated_data
            )
        except runs.VerificationRefused as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=exc.status_code)
        body = {
            "id": run.pk,
            "state": runs.latest_event(run).state,
            "deduplicated": deduplicated,
            "status_url": status_url(run),
        }
        return Response(body, status=status.HTTP_202_ACCEPTED)


class AuditVerificationDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Audit verification"],
        summary="Read one audit verification run's latest state and coverage",
        responses={200: VerificationRunSerializer, **ERRORS},
    )
    def get(self, request, makerspace_id, run_id):
        makerspace = _scoped_makerspace(request.user, makerspace_id)
        run = AuditVerificationRun.objects.filter(makerspace=makerspace, pk=run_id).first()
        if run is None:
            raise Http404
        return Response(_payload(request, run))
