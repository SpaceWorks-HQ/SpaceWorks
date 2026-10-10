from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.list_options import StaffListPagination
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.staff_list_scope import ENTITY_ACTIONS, require_entity, visible_space
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.operations.models_saved_views import SavedView
from apps.operations.serializers_saved_views import SavedViewListSerializer, SavedViewSerializer

ERRORS = {code: ErrorSerializer for code in (400, 401, 403, 404, 423, 503)}


def accessible_views(actor, space):
    # Action scope also admits organization-derived staff; entity checks are applied
    # separately, so a shared preference can never confer a new list permission.
    ids = rbac.makerspaces_for_actions(actor, *{a for actions in ENTITY_ACTIONS.values() for a in actions})
    rows = SavedView.objects.filter(makerspace=space).select_related("owner")
    if ids is not rbac.ALL:
        rows = rows.filter(makerspace_id__in=ids)
    return rows.filter(Q(owner=actor) | Q(shared=True))


def validate_share(actor, space, shared):
    if shared and not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, space.pk):
        raise PermissionDenied("Only makerspace managers may publish shared views.")


class SavedViewListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Staff lists"], request=None, parameters=[OpenApiParameter("entity", str, required=True, enum=list(ENTITY_ACTIONS)), OpenApiParameter("page", int)], responses={200: SavedViewListSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = visible_space(request.user, makerspace_id)
        entity = request.query_params.get("entity", "")
        if entity not in ENTITY_ACTIONS:
            raise ValidationError({"entity": "Choose a staff list."})
        require_entity(request.user, space, entity)
        pager = StaffListPagination()
        page = pager.paginate_queryset(accessible_views(request.user, space).filter(entity=entity), request, view=self)
        return pager.get_paginated_response(SavedViewSerializer(page, many=True).data)

    @extend_schema(tags=["Staff lists"], request=SavedViewSerializer, responses={201: SavedViewSerializer, **ERRORS})
    @transaction.atomic
    def post(self, request, makerspace_id):
        space = visible_space(request.user, makerspace_id)
        payload = SavedViewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        require_entity(request.user, space, payload.validated_data["entity"])
        validate_share(request.user, space, payload.validated_data.get("shared", False))
        view = payload.save(makerspace=space, owner=request.user)
        audit.record(request.user, "saved_view.created", makerspace=space, target=view)
        if view.shared:
            audit.record(request.user, "saved_view.shared", makerspace=space, target=view)
        return Response(SavedViewSerializer(view).data, status=201)


class SavedViewDetailView(APIView):
    permission_classes = [IsActiveStaff]

    def row(self, request, makerspace_id, pk, *, lock=False):
        space = visible_space(request.user, makerspace_id)
        rows = accessible_views(request.user, space)
        if lock:
            rows = rows.select_for_update()
        row = get_object_or_404(rows, pk=pk)
        require_entity(request.user, space, row.entity)
        return row, space

    @extend_schema(tags=["Staff lists"], request=None, responses={200: SavedViewSerializer, **ERRORS})
    def get(self, request, makerspace_id, pk):
        row, _space = self.row(request, makerspace_id, pk)
        return Response(SavedViewSerializer(row).data)

    @extend_schema(tags=["Staff lists"], request=SavedViewSerializer, responses={200: SavedViewSerializer, **ERRORS})
    @transaction.atomic
    def patch(self, request, makerspace_id, pk):
        row, space = self.row(request, makerspace_id, pk, lock=True)
        if row.owner_id != request.user.pk:
            raise PermissionDenied("Only the owner may edit this view.")
        payload = SavedViewSerializer(row, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        require_entity(request.user, space, payload.validated_data.get("entity", row.entity))
        shared = payload.validated_data.get("shared", row.shared)
        # Editing a published view is publishing too, even if shared wasn't sent.
        validate_share(request.user, space, shared)
        was_shared = row.shared
        payload.save()
        audit.record(request.user, "saved_view.updated", makerspace=space, target=row)
        if was_shared != row.shared:
            if row.shared:
                audit.record(request.user, "saved_view.shared", makerspace=space, target=row)
            else:
                audit.record(request.user, "saved_view.unshared", makerspace=space, target=row)
        return Response(SavedViewSerializer(row).data)

    @extend_schema(tags=["Staff lists"], request=None, responses={204: None, **ERRORS})
    @transaction.atomic
    def delete(self, request, makerspace_id, pk):
        row, space = self.row(request, makerspace_id, pk, lock=True)
        if row.owner_id != request.user.pk:
            raise PermissionDenied("Only the owner may delete this view.")
        if row.shared:
            validate_share(request.user, space, True)
        audit.record(request.user, "saved_view.deleted", makerspace=space, target=row)
        row.delete()
        return Response(status=204)
