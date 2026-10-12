"""Space managers configure admissions; membership coordinators review applications."""
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.views_member_memberships import _makerspace
from apps.admin_api.views_roles import ERRORS as ROLE_ERRORS
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_admission_settings import settings_for, update_settings
from apps.makerspaces.serializers_admission import AdmissionSettingsSerializer

ERRORS = {**ROLE_ERRORS, 423: ROLE_ERRORS[400], 503: ROLE_ERRORS[400]}


class AdminMembershipAdmissionView(APIView):
    permission_classes = [IsActiveStaff]

    def _space(self, request, makerspace_id):
        space = _makerspace(request.user, makerspace_id, rbac.Action.MANAGE_MAKERSPACE)
        require_module(space, "membership")
        return space

    @extend_schema(description="Requires manage_makerspace; settings are separate from manage_members.", tags=["Admin memberships"], responses={200: AdmissionSettingsSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = self._space(request, makerspace_id)
        return Response(AdmissionSettingsSerializer(settings_for(space)).data)

    @extend_schema(description="Requires manage_makerspace. Paid admissions require charge tracking, not an online gateway.", tags=["Admin memberships"], request=AdmissionSettingsSerializer, responses={200: AdmissionSettingsSerializer, **ERRORS})
    def patch(self, request, makerspace_id):
        space = self._space(request, makerspace_id)
        serializer = AdmissionSettingsSerializer(data=request.data, partial=True, context={"makerspace": space})
        serializer.is_valid(raise_exception=True)
        row = update_settings(request.user, space, serializer.validated_data)
        return Response(AdmissionSettingsSerializer(row).data)
