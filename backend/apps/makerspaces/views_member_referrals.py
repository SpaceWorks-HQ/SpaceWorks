from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import active_user
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.membership_services import refer_membership
from apps.makerspaces.serializers_memberships import ReferralCreateSerializer, ReferralOutcomeSerializer
from apps.makerspaces.servability import servable_queryset


ERRORS = {400: ErrorSerializer, 401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer, 409: ErrorSerializer}


class MemberReferralView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Memberships"],
        request=ReferralCreateSerializer,
        responses={201: ReferralOutcomeSerializer, **ERRORS},
    )
    def post(self, request, makerspace_id):
        if not active_user(request.user):
            raise PermissionDenied()
        makerspace = get_object_or_404(
            servable_queryset(), pk=makerspace_id
        )
        serializer = ReferralCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refer_membership(request.user, makerspace, serializer.validated_data["invite_email"])
        return Response({"state": "invited"}, status=status.HTTP_201_CREATED)
