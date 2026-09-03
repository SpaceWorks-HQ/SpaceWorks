from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.organizations import governance, services_invitations, services_profiles
from apps.organizations.access import require_governance, visible_organizations
from apps.organizations.models import OrganizationInvitation, OrganizationMembership
from apps.organizations.serializers_admin import (
    OrganizationDetailSerializer,
    OrganizationInvitationCreateSerializer,
    OrganizationInvitationCreatedSerializer,
    OrganizationInvitationListSerializer,
    OrganizationInvitationSerializer,
    OrganizationListSerializer,
    OrganizationMembershipListSerializer,
    OrganizationMembershipSerializer,
    OrganizationProfileUpdateSerializer,
    OrganizationSummarySerializer,
)


ERRORS = {
    401: OpenApiResponse(ErrorSerializer, description="Authentication is required."),
    403: OpenApiResponse(ErrorSerializer, description="Organization authority is required."),
    404: OpenApiResponse(ErrorSerializer, description="Organization not found."),
}
WRITE_ERRORS = {
    **ERRORS,
    400: OpenApiResponse(description="Invalid organization data."),
    409: OpenApiResponse(ErrorSerializer, description="Organization state conflict."),
}


def _organizations_for(actor):
    actor_memberships = OrganizationMembership.objects.filter(
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
    )
    return visible_organizations(actor).prefetch_related(
        Prefetch("memberships", queryset=actor_memberships, to_attr="actor_memberships")
    )


def _organization(actor, pk):
    return get_object_or_404(_organizations_for(actor), pk=pk)


def _page(queryset, request, view, serializer, **context):
    paginator = PageNumberPagination()
    rows = paginator.paginate_queryset(queryset, request, view=view)
    return paginator.get_paginated_response(serializer(rows, many=True, context=context).data)


class OrganizationListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        operation_id="admin_organizations_list",
        tags=["Admin organizations"],
        summary="List organizations visible to the actor",
        request=None,
        responses={200: OrganizationListSerializer, **ERRORS},
    )
    def get(self, request):
        return _page(
            _organizations_for(request.user).order_by("name", "id"),
            request,
            self,
            OrganizationSummarySerializer,
            actor=request.user,
        )


class OrganizationDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        operation_id="admin_organizations_retrieve",
        tags=["Admin organizations"],
        summary="Retrieve organization governance details",
        request=None,
        responses={200: OrganizationDetailSerializer, **ERRORS},
    )
    def get(self, request, pk):
        organization = _organization(request.user, pk)
        return Response(
            OrganizationDetailSerializer(organization, context={"actor": request.user}).data
        )

    @extend_schema(
        tags=["Admin organizations"],
        summary="Update an organization public profile",
        request=OrganizationProfileUpdateSerializer,
        responses={200: OrganizationDetailSerializer, **WRITE_ERRORS},
    )
    def patch(self, request, pk):
        organization = _organization(request.user, pk)
        serializer = OrganizationProfileUpdateSerializer(
            organization, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = services_profiles.update_profile(
            organization, actor=request.user, **serializer.validated_data
        )
        updated.actor_memberships = list(
            OrganizationMembership.objects.filter(
                organization=updated,
                user=request.user,
                status=OrganizationMembership.Status.ACTIVE,
            )
        )
        return Response(
            OrganizationDetailSerializer(updated, context={"actor": request.user}).data
        )


class OrganizationMembershipListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin organizations"],
        summary="List organization memberships",
        request=None,
        responses={200: OrganizationMembershipListSerializer, **ERRORS},
    )
    def get(self, request, pk):
        organization = _organization(request.user, pk)
        require_governance(
            request.user, organization, governance.MANAGE_ORGANIZATION_MEMBERS
        )
        queryset = organization.memberships.select_related("user").order_by("user__username", "id")
        return _page(queryset, request, self, OrganizationMembershipSerializer)


class OrganizationInvitationListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin organizations"],
        summary="List organization invitations without bearer tokens",
        request=None,
        responses={200: OrganizationInvitationListSerializer, **ERRORS},
    )
    def get(self, request, pk):
        organization = _organization(request.user, pk)
        require_governance(
            request.user, organization, governance.MANAGE_ORGANIZATION_MEMBERS
        )
        return _page(organization.invitations.all(), request, self, OrganizationInvitationSerializer)

    @extend_schema(
        tags=["Admin organizations"],
        summary="Create a single-use organization invitation",
        request=OrganizationInvitationCreateSerializer,
        responses={201: OrganizationInvitationCreatedSerializer, **WRITE_ERRORS},
    )
    def post(self, request, pk):
        organization = _organization(request.user, pk)
        serializer = OrganizationInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation, token = services_invitations.create_invitation(
            organization, actor=request.user, **serializer.validated_data
        )
        payload = OrganizationInvitationSerializer(invitation).data
        payload.update(
            {
                "token": token,
                "redeem_path": "/api/v1/auth/organization-invitations/redeem/",
            }
        )
        return Response(payload, status=status.HTTP_201_CREATED)


class OrganizationInvitationRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin organizations"],
        summary="Revoke an unused organization invitation",
        request=None,
        responses={204: None, **WRITE_ERRORS},
    )
    def delete(self, request, pk):
        invitation = get_object_or_404(
            OrganizationInvitation.objects.select_related("organization").filter(
                organization__in=visible_organizations(request.user)
            ),
            pk=pk,
        )
        services_invitations.revoke_invitation(invitation, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
