"""Community admission reads and mutations, scoped to the person or active voucher."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import active_user
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_admission_settings import application_schema_for, settings_for
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest
from apps.makerspaces.serializers_admission import (
    AdmissionExportSerializer, AdmissionRequestSerializer, AdmissionVouchOutcomeSerializer, PublicAdmissionSerializer,
)
from apps.makerspaces.servability import servable_queryset
from apps.tenant_migration.gate_runtime import tenant_write

ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer,
          423: ErrorSerializer, 429: ErrorSerializer, 503: ErrorSerializer}


def own_admission_space(user, makerspace_id):
    if not active_user(user):
        raise PermissionDenied()
    space = get_object_or_404(servable_queryset(), pk=makerspace_id)
    require_module(space, "membership")
    if MakerspaceMembership.objects.filter(makerspace=space, user=user, status="revoked").exists() and not MembershipRequest.objects.filter(
        makerspace=space, user=user, admission_managed=True, state__in=("requested", "awaiting_vouches", "awaiting_payment"),
    ).exists():
        raise PermissionDenied()
    return space


def public_admission_payload(space):
    from apps.makerspaces.membership_admission_settings import vouching_on
    policy = settings_for(space)
    plan = policy.default_plan
    return {
        "join_mode": "approval" if policy.join_mode == "vouch" and not vouching_on(space, policy) else policy.join_mode,
        "vouches_required": policy.vouches_required,
        "application_schema": application_schema_for(space, policy),
        "default_plan": {"id": plan.pk, "name": plan.name, "amount": str(plan.amount), "currency": plan.currency} if plan else None,
        "joining_fee": policy.joining_fee, "joining_fee_currency": policy.joining_fee_currency,
        "payment_timing": policy.payment_timing,
    }


class PublicAdmissionView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(auth=[], tags=["Memberships"], responses={200: PublicAdmissionSerializer, **ERRORS})
    def get(self, request, makerspace_slug):
        space = get_object_or_404(servable_queryset(), slug=makerspace_slug)
        require_module(space, "membership")
        return Response(PublicAdmissionSerializer(public_admission_payload(space)).data)


class MemberAdmissionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Memberships"], responses={200: AdmissionRequestSerializer(allow_null=True), **ERRORS})
    def get(self, request, makerspace_id):
        space = own_admission_space(request.user, makerspace_id)
        row = MembershipRequest.objects.filter(makerspace=space, user=request.user).select_related("admission_payment").prefetch_related("vouches__voucher").first()
        return Response(AdmissionRequestSerializer(row).data if row else None)


class MemberAdmissionExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Memberships"], responses={200: AdmissionExportSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        if not active_user(request.user):
            raise PermissionDenied()
        space = get_object_or_404(servable_queryset(), pk=makerspace_id)
        require_module(space, "membership")
        rows = MembershipRequest.objects.filter(makerspace=space, user=request.user).select_related("admission_payment").prefetch_related("vouches__voucher")
        # GET bypasses the HTTP mutation boundary, but exporting records an audit row.
        with tenant_write(space.pk):
            data = AdmissionRequestSerializer(rows, many=True).data
            audit.record(request.user, "membership.application_exported", makerspace=space,
                         meta={"request_count": len(data)})
        return Response({"requests": data})


class MemberAdmissionCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, tags=["Memberships"], responses={200: AdmissionRequestSerializer, **ERRORS})
    def post(self, request, makerspace_id, request_id):
        space = own_admission_space(request.user, makerspace_id)
        with transaction.atomic():
            space = Makerspace.objects.select_for_update().get(pk=space.pk)
            require_module(space, "membership")
            row = get_object_or_404(MembershipRequest.objects.select_for_update(), pk=request_id, makerspace=space, user=request.user)
            from apps.makerspaces.membership_admission_payments import close_admission
            row = close_admission(request.user, row)
        return Response(AdmissionRequestSerializer(row).data)


class MemberAdmissionVouchView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "membership_request"

    @extend_schema(request=None, tags=["Memberships"], responses={200: AdmissionVouchOutcomeSerializer, **ERRORS})
    def post(self, request, makerspace_id, request_id):
        if not active_user(request.user):
            raise PermissionDenied()
        space = get_object_or_404(rbac.scope_by_makerspace(request.user, servable_queryset(), makerspace_field="id"), pk=makerspace_id)
        require_module(space, "membership")
        row = get_object_or_404(rbac.scope_by_makerspace(request.user, MembershipRequest.objects.all()), makerspace=space, pk=request_id)
        from apps.makerspaces.membership_vouching import vouch_for_request
        vouch_for_request(request.user, row)
        row.refresh_from_db()
        return Response(AdmissionVouchOutcomeSerializer(row).data)
