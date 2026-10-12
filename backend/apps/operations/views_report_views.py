"""A saved report preference never confers authority on its owner or its reader."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.list_options import StaffListPagination
from apps.admin_api.permissions import IsActiveStaff, active_user, require_action
from apps.audit import services as audit
from apps.makerspaces.guards import require_feature, require_module, require_module_locked
from apps.operations.models_saved_views import SavedView
from apps.operations.report_registry import REPORT_REGISTRY
from apps.operations.serializers_report_views import SavedReportViewListSerializer, SavedReportViewSerializer
from apps.operations.serializers_reports import ReportErrorSerializer
from apps.operations.views_report_helpers import _makerspace_for_catalog
from apps.operations.views_saved_views import validate_share

ERRORS = {code: ReportErrorSerializer for code in (400, 401, 403, 404, 423, 503)}


def space_for_views(actor, pk, *, lock=False):
    space = _makerspace_for_catalog(actor, pk)
    space = require_module_locked(space, "reports") if lock else require_module(space, "reports")
    require_feature(space, "reports.saved_views")
    return space


def authorize_view(actor, space, state):
    definition = REPORT_REGISTRY.get(state.get("report_key"))
    if definition is None:
        raise PermissionDenied("The saved report is unavailable.")
    require_action(actor, definition.required_action, space.pk)
    for module in definition.required_modules:
        require_module(space, module)
    return definition


def accessible_report_views(actor, space):
    keys = [key for key, definition in REPORT_REGISTRY.items()
            if definition.previewable and rbac.can(actor, definition.required_action, space.pk)]
    rows = SavedView.objects.none()
    for action in {definition.required_action for definition in REPORT_REGISTRY.values()}:
        rows = rows | rbac.scope_by_action(actor, action, SavedView.objects.all())
    return rows.filter(makerspace=space, entity="report", state__report_key__in=keys).filter(
        Q(owner=actor) | Q(shared=True),
    ).select_related("owner").order_by("name", "id")


def owner_authorized(row, space):
    definition = REPORT_REGISTRY.get(row.state.get("report_key"))
    return bool(definition and active_user(row.owner)
                and rbac.can(row.owner, definition.required_action, space.pk))


class SavedReportViewListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Reports"], request=None, parameters=[OpenApiParameter("page", int)],
                   responses={200: SavedReportViewListSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = space_for_views(request.user, makerspace_id)
        owners, rows = {}, []
        for row in accessible_report_views(request.user, space):
            key = (row.owner_id, row.state.get("report_key"))
            if key not in owners:
                owners[key] = owner_authorized(row, space)
            if owners[key]:
                rows.append(row)
        pager = StaffListPagination()
        page = pager.paginate_queryset(rows, request, view=self)
        return pager.get_paginated_response(SavedReportViewSerializer(page, many=True).data)

    @extend_schema(tags=["Reports"], request=SavedReportViewSerializer, responses={201: SavedReportViewSerializer, **ERRORS})
    @transaction.atomic
    def post(self, request, makerspace_id):
        space = space_for_views(request.user, makerspace_id, lock=True)
        payload = SavedReportViewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        authorize_view(request.user, space, payload.validated_data["state"])
        validate_share(request.user, space, payload.validated_data.get("shared", False))
        row = payload.save(makerspace=space, owner=request.user, entity="report")
        audit.record(request.user, "saved_view.created", makerspace=space, target=row)
        if row.shared:
            audit.record(request.user, "saved_view.shared", makerspace=space, target=row)
        return Response(SavedReportViewSerializer(row).data, status=201)


class SavedReportViewDetailView(APIView):
    permission_classes = [IsActiveStaff]

    def row(self, request, makerspace_id, pk, *, lock=False):
        space = space_for_views(request.user, makerspace_id, lock=lock)
        rows = accessible_report_views(request.user, space)
        if lock:
            rows = rows.select_for_update(of=("self",))
        row = get_object_or_404(rows, pk=pk)
        authorize_view(request.user, space, row.state)
        if not owner_authorized(row, space):
            raise PermissionDenied("The view owner can no longer open this report.")
        return row, space

    @extend_schema(tags=["Reports"], request=None, responses={200: SavedReportViewSerializer, **ERRORS})
    def get(self, request, makerspace_id, pk):
        row, _space = self.row(request, makerspace_id, pk)
        return Response(SavedReportViewSerializer(row).data)

    @extend_schema(tags=["Reports"], request=SavedReportViewSerializer, responses={200: SavedReportViewSerializer, **ERRORS})
    @transaction.atomic
    def patch(self, request, makerspace_id, pk):
        row, space = self.row(request, makerspace_id, pk, lock=True)
        if row.owner_id != request.user.pk:
            raise PermissionDenied("Only the owner may edit this view.")
        payload = SavedReportViewSerializer(row, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        authorize_view(request.user, space, payload.validated_data.get("state", row.state))
        validate_share(request.user, space, payload.validated_data.get("shared", row.shared))
        was_shared = row.shared
        payload.save()
        audit.record(request.user, "saved_view.updated", makerspace=space, target=row)
        if was_shared != row.shared:
            audit.record(request.user, "saved_view.shared" if row.shared else "saved_view.unshared", makerspace=space, target=row)
        return Response(SavedReportViewSerializer(row).data)

    @extend_schema(tags=["Reports"], request=None, responses={204: None, **ERRORS})
    @transaction.atomic
    def delete(self, request, makerspace_id, pk):
        row, space = self.row(request, makerspace_id, pk, lock=True)
        if row.owner_id != request.user.pk:
            raise PermissionDenied("Only the owner may delete this view.")
        audit.record(request.user, "saved_view.deleted", makerspace=space, target=row)
        row.delete()
        return Response(status=204)
