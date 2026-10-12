from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import services_staff_invitations as service
from apps.accounts.permissions import HasMakerspaceAction
from apps.accounts.rbac import Action
from apps.accounts.serializers_staff_invitations import (
    StaffInvitationAcceptSerializer, StaffInvitationAcceptedSerializer,
    StaffInvitationCreateSerializer, StaffInvitationDeliverySerializer, StaffInvitationSerializer,
)
from apps.accounts.staff_invitation_acceptance import accept
from apps.accounts.staff_invitation_delivery import deliver
from apps.openapi_errors import errors

GATE_WRITE_ERRORS = {
    423: OpenApiResponse(description="Makerspace writes are frozen for tenant migration."),
    **errors(503),
}


class StaffInvitationListView(GenericAPIView):
    permission_classes = [IsAuthenticated, HasMakerspaceAction]
    required_action = Action.MANAGE_MAKERSPACE
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "staff_invite"
    serializer_class = StaffInvitationSerializer

    def get_queryset(self):
        return service.scoped(self.request.user).filter(
            makerspace_id=self.kwargs["makerspace_id"]).select_related("role").order_by("-created_at", "-id")

    @extend_schema(tags=["Staff invitations"], responses={200: StaffInvitationSerializer(many=True), **errors(400, 401, 403, 404, 429)})
    def get(self, request, makerspace_id):
        from apps.makerspaces.models import Makerspace
        from apps.makerspaces.platform import feature_enabled
        from apps.accounts import rbac
        from rest_framework.exceptions import ValidationError
        space = get_object_or_404(rbac.scope_by_action(request.user, self.required_action,
                                                      Makerspace.objects.all(), "id"), pk=makerspace_id)
        if not feature_enabled(space, "staff.invitations"):
            raise ValidationError("Staff invitations are disabled for this makerspace.")
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(tags=["Staff invitations"], request=StaffInvitationCreateSerializer,
                   responses={201: StaffInvitationDeliverySerializer, **errors(400, 401, 403, 404, 429), **GATE_WRITE_ERRORS})
    def post(self, request, makerspace_id):
        serializer = StaffInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row, raw = service.create(request.user, makerspace_id, **serializer.validated_data)
        response = Response({**StaffInvitationSerializer(row).data, **deliver(row, raw)}, status=201)
        response["Cache-Control"] = "no-store"
        return response


class StaffInvitationRevokeView(StaffInvitationListView):
    @extend_schema(tags=["Staff invitations"], request=None,
                   responses={200: StaffInvitationSerializer, **errors(400, 401, 403, 404, 429), **GATE_WRITE_ERRORS})
    def post(self, request, makerspace_id, invitation_id):
        row, _ = service.mutate(request.user, get_object_or_404(self.get_queryset(), pk=invitation_id))
        return Response(StaffInvitationSerializer(row).data)

    http_method_names = ["post", "options"]


class StaffInvitationResendView(StaffInvitationRevokeView):
    @extend_schema(tags=["Staff invitations"], request=None,
                   responses={200: StaffInvitationDeliverySerializer, **errors(400, 401, 403, 404, 429), **GATE_WRITE_ERRORS})
    def post(self, request, makerspace_id, invitation_id):
        row, raw = service.mutate(request.user, get_object_or_404(self.get_queryset(), pk=invitation_id), resend=True)
        response = Response({**StaffInvitationSerializer(row).data, **deliver(row, raw)})
        response["Cache-Control"] = "no-store"
        return response


class StaffInvitationAcceptView(GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "staff_invite_accept"
    serializer_class = StaffInvitationAcceptSerializer

    @extend_schema(tags=["Staff invitations"], auth=[], request=StaffInvitationAcceptSerializer,
                   responses={200: StaffInvitationAcceptedSerializer, **errors(400, 401, 403, 429), **GATE_WRITE_ERRORS})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(accept(request, **serializer.validated_data))
