"""Read-only first-run progress, derived from tenant rows rather than browser ticks."""
from django.shortcuts import get_object_or_404
from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models_staff_invitations import StaffInvitation
from apps.admin_api.permissions import IsActiveStaff
from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct
from apps.makerspaces.servability import servable_queryset
from apps.openapi_errors import errors


class SetupStateSerializer(serializers.Serializer):
    profile_set = serializers.BooleanField()
    hours_set = serializers.BooleanField()
    first_item_added = serializers.BooleanField()
    staff_invited = serializers.BooleanField()
    modules_chosen = serializers.BooleanField()


class MakerspaceSetupStateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Makerspaces"], summary="Read derived makerspace setup progress",
                   request=None, responses={200: SetupStateSerializer, **errors(401, 403, 404)})
    def get(self, request, makerspace_id):
        action = rbac.Action.MANAGE_MAKERSPACE
        spaces = rbac.scope_by_action(request.user, action, servable_queryset(), field="id")
        space = get_object_or_404(spaces, pk=makerspace_id)
        def scoped(query):
            return rbac.scope_by_action(request.user, action, query).filter(makerspace=space)

        hours = space.opening_hours or {}
        data = {
            "profile_set": bool(space.name.strip() and space.location.strip()),
            "hours_set": bool(hours.get("weekly") or hours.get("exceptions")),
            "first_item_added": scoped(InventoryProduct.objects.all()).exists(),
            "staff_invited": scoped(StaffInvitation.objects.filter(revoked_at__isnull=True)).exists(),
            # Defaults are installed automatically: they do not prove a choice.
            "modules_chosen": scoped(AuditLog.objects.filter(
                action="makerspace.capabilities_changed", meta__before__has_key="modules", meta__after__has_key="modules",
            ).exclude(meta__before__modules=F("meta__after__modules"))).exists(),
        }
        response = Response(SetupStateSerializer(data).data)
        response["Cache-Control"] = "no-store"
        return response
