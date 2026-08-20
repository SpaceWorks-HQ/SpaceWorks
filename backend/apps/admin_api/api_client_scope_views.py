from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.api_client_serializers import ApiClientScopeOptionSerializer
from apps.admin_api.permissions import IsActiveStaff
from apps.apiclients.scope_grants import (
    actor_may_grant_privileged_scopes,
    scope_catalog,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.models import Makerspace


ERRORS = {401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


def _visible_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_MAKERSPACE,
            Makerspace.objects.all(),
            field="id",
        ),
        pk=makerspace_id,
    )
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk):
        raise PermissionDenied()
    return makerspace


class ApiClientScopeCatalogView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["API clients"],
        summary="List API-client scope grant options",
        responses={200: ApiClientScopeOptionSerializer(many=True), **ERRORS},
    )
    def get(self, request, makerspace_id):
        _visible_makerspace(request.user, makerspace_id)
        privileged = actor_may_grant_privileged_scopes(request.user, makerspace_id)
        return Response(
            ApiClientScopeOptionSerializer(
                scope_catalog(privileged=privileged), many=True
            ).data
        )
