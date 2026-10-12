from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.filters import BaseFilterBackend
from apps.admin_api.list_options import ListIdentityFilter, StableOrderingFilter
from django.db.models import Q
from django.conf import settings

from apps.accounts import rbac
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.permissions import CanReviewRequest, CanViewHandoverQueue
from apps.hardware_requests.serializers import AdminRequestSerializer
from apps.hardware_requests.view_helpers import (
    ADMIN_LIST_ERROR_RESPONSES,
    ERROR_400,
    ERROR_401,
    request_queryset,
    handover_surface_module,
)
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module

# Staff search the queues by who borrowed / what for. Scoped to the queue's own
# makerspace filter already, so this only narrows within the tenant.
REQUEST_SEARCH_FIELDS = ["requested_for"]


class ScopedPiiSearchFilter(BaseFilterBackend):
    def get_schema_operation_parameters(self, view):
        # Keep the `search` query parameter documented in OpenAPI even though this
        # is a custom backend (blind-index/plaintext resolution happens internally).
        return [{
            "name": "search",
            "required": False,
            "in": "query",
            "description": "A search term (requested-for, requester name/email).",
            "schema": {"type": "string"},
        }]

    def filter_queryset(self, request, queryset, view):
        term = request.query_params.get("search", "").strip()
        if not term:
            return queryset
        if not settings.PII_ENCRYPTION_ENABLED:
            return queryset.filter(Q(requested_for__icontains=term) | Q(requester_name__icontains=term) | Q(requester_contact_email__icontains=term))
        from rest_framework.exceptions import ValidationError

        from apps.encryption.search import indexed_candidates, legacy_plaintext_candidates, verified_ids
        makerspace_id = view.kwargs["makerspace_id"]
        ids = set()
        for field_name, exact in (("requester_name", False), ("requester_contact_email", True)):
            try:
                candidates = indexed_candidates(makerspace_id=makerspace_id, model_label="hardware_requests.HardwareRequest", field_name=field_name, term=term, exact=exact)
            except ValidationError:  # e.g. name term shorter than a trigram
                candidates = []
            ids.update(verified_ids(queryset.filter(pk__in=candidates), field_name=field_name, term=term, exact=exact))
            # During the dual-read rollout, pre-backfill rows have no index yet.
            if settings.PII_ENCRYPTION_DUAL_READ:
                ids.update(legacy_plaintext_candidates(queryset, field_name=field_name, term=term, exact=exact))
        return queryset.filter(Q(requested_for__icontains=term) | Q(pk__in=ids))


class PendingRequestsView(generics.ListAPIView):
    permission_classes = [CanReviewRequest]
    serializer_class = AdminRequestSerializer
    filter_backends = [ListIdentityFilter, ScopedPiiSearchFilter, StableOrderingFilter]
    ordering_fields = ["created_at", "return_due_at", "status"]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        makerspace = _require_action(self.request.user, rbac.Action.ACCEPT_REQUEST, makerspace_id)
        require_module(makerspace, "request_workflow")
        return (
            rbac.scope_by_action(self.request.user, rbac.Action.ACCEPT_REQUEST, request_queryset())
            .filter(
                makerspace_id=makerspace_id,
                status=HardwareRequest.Status.PENDING_APPROVAL,
            )
            .order_by("-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List pending borrow requests",
        responses={200: AdminRequestSerializer(many=True), 400: ERROR_400, 401: ERROR_401, **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AcceptedRequestsView(generics.ListAPIView):
    permission_classes = [CanViewHandoverQueue]
    serializer_class = AdminRequestSerializer
    filter_backends = [ListIdentityFilter, ScopedPiiSearchFilter, StableOrderingFilter]
    ordering_fields = ["created_at", "return_due_at", "status"]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        makerspace = _require_action(self.request.user, rbac.Action.ISSUE_REQUEST, makerspace_id)
        require_module(makerspace, handover_surface_module(self.request))
        return (
            rbac.scope_by_action(self.request.user, rbac.Action.ISSUE_REQUEST, request_queryset())
            .filter(
                makerspace_id=makerspace_id,
                status=HardwareRequest.Status.ACCEPTED,
            )
            .order_by("-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List accepted requests awaiting issue",
        responses={200: AdminRequestSerializer(many=True), 400: ERROR_400, 401: ERROR_401, **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ActiveLoansView(generics.ListAPIView):
    permission_classes = [CanViewHandoverQueue]
    serializer_class = AdminRequestSerializer
    filter_backends = [ListIdentityFilter, ScopedPiiSearchFilter, StableOrderingFilter]
    ordering_fields = ["created_at", "return_due_at", "status"]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        makerspace = _require_action(self.request.user, rbac.Action.ISSUE_REQUEST, makerspace_id)
        require_module(makerspace, handover_surface_module(self.request))
        return (
            rbac.scope_by_action(self.request.user, rbac.Action.ISSUE_REQUEST, request_queryset())
            .filter(
                makerspace_id=makerspace_id,
                status__in=[
                    HardwareRequest.Status.ISSUED,
                    HardwareRequest.Status.PARTIALLY_RETURNED,
                ],
            )
            .order_by("-issued_at", "-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List active loans awaiting return",
        responses={200: AdminRequestSerializer(many=True), 400: ERROR_400, 401: ERROR_401, **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class RequestHistoryView(generics.ListAPIView):
    # Terminal requests (returned / rejected / closed_with_issue) had no staff surface -
    # once a loan was returned or a request rejected it vanished from every queue, hiding
    # the accountability-bearing closed_with_issue loans (damaged/missing units). Gated on
    # ISSUE_REQUEST (the handover-queue viewers) to match the accepted/active loan views.
    permission_classes = [CanViewHandoverQueue]
    serializer_class = AdminRequestSerializer
    filter_backends = [ListIdentityFilter, ScopedPiiSearchFilter, StableOrderingFilter]
    ordering_fields = ["created_at", "return_due_at", "status"]
    search_fields = REQUEST_SEARCH_FIELDS

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        makerspace = _require_action(self.request.user, rbac.Action.ISSUE_REQUEST, makerspace_id)
        require_module(makerspace, handover_surface_module(self.request))
        return (
            rbac.scope_by_action(self.request.user, rbac.Action.ISSUE_REQUEST, request_queryset())
            .filter(
                makerspace_id=makerspace_id,
                status__in=[
                    HardwareRequest.Status.RETURNED,
                    HardwareRequest.Status.REJECTED,
                    HardwareRequest.Status.CLOSED_WITH_ISSUE,
                ],
            )
            .order_by("-updated_at", "-created_at")
        )

    @extend_schema(
        tags=["Admin requests"],
        summary="List terminal request history (returned / rejected / closed with issue)",
        responses={200: AdminRequestSerializer(many=True), 400: ERROR_400, 401: ERROR_401, **ADMIN_LIST_ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


def _require_action(user, action, makerspace_id):
    # Reuse the authorized tenant for the module check instead of fetching it twice.
    scoped = rbac.scope_by_action(user, action, Makerspace.objects.all(), field="id")
    return get_object_or_404(scoped, pk=makerspace_id)
