"""Staff console: issue, reissue, revoke, print, resolve and template member cards.

Gated by ACTIONS (`MANAGE_MEMBER_CARDS`, `SCAN_MEMBER_CARDS`), scoped through `rbac`.
"""
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces import member_card_printing, member_card_services, member_card_templates
from apps.makerspaces.guards import require_module
from apps.makerspaces.member_card_serializers import (
    MemberCardIssueSerializer,
    MemberCardPrintSerializer,
    MemberCardReissueSerializer,
    MemberCardResolveResultSerializer,
    MemberCardResolveSerializer,
    MemberCardRevokeSerializer,
    MemberCardSerializer,
    MemberCardTemplateSerializer,
)
from apps.makerspaces.member_card_views import snapshot_for
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MemberCard

ERRORS = {403: OpenApiResponse(description="Missing member-card action."), 404: OpenApiResponse(description="Not found.")}
TAG = "Admin memberships"


def _makerspace_for(actor, action, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_action(actor, action, Makerspace.objects.all(), field="id"), pk=makerspace_id
    )
    require_module(makerspace, "membership")
    return makerspace


def _card_for(actor, action, pk):
    return get_object_or_404(
        rbac.scope_by_action(actor, action, MemberCard.objects.select_related("makerspace", "membership__assigned_role")),
        pk=pk,
    )


class _Pagination(PageNumberPagination):
    page_size = 24


class MemberCardListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="List member cards", request=None,
                   parameters=[OpenApiParameter("status", str, OpenApiParameter.QUERY, description="active | revoked")],
                   responses={200: MemberCardSerializer(many=True), **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = _makerspace_for(request.user, rbac.Action.SCAN_MEMBER_CARDS, makerspace_id)
        queryset = MemberCard.objects.filter(makerspace=makerspace).select_related("membership__user")
        wanted = request.query_params.get("status")
        if wanted == "active":
            queryset = queryset.filter(revoked_at__isnull=True, membership__isnull=False)
        elif wanted == "revoked":
            queryset = queryset.filter(revoked_at__isnull=False)
        paginator = _Pagination()
        page = paginator.paginate_queryset(queryset.order_by("card_number"), request, view=self)
        return paginator.get_paginated_response(MemberCardSerializer(page, many=True).data)


class MemberCardIssueView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Issue a card to a membership", request=MemberCardIssueSerializer,
                   responses={201: MemberCardSerializer, **ERRORS})
    def post(self, request, makerspace_id, membership_id):
        makerspace = _makerspace_for(request.user, rbac.Action.MANAGE_MEMBER_CARDS, makerspace_id)
        membership = get_object_or_404(MakerspaceMembership, pk=membership_id, makerspace=makerspace)
        serializer = MemberCardIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = member_card_services.issue_card(
            request.user, membership, printed_name=serializer.validated_data.get("printed_name", "")
        )
        return Response(MemberCardSerializer(card).data, status=status.HTTP_201_CREATED)


class MemberCardReissueView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Reissue (rotate the QR of) a card", request=MemberCardReissueSerializer,
                   responses={200: MemberCardSerializer, **ERRORS})
    def post(self, request, pk):
        card = _card_for(request.user, rbac.Action.MANAGE_MEMBER_CARDS, pk)
        serializer = MemberCardReissueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = member_card_services.reissue_card(request.user, card, reason=serializer.validated_data["reason"])
        return Response(MemberCardSerializer(card).data)


class MemberCardRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Revoke a card (redacts name and photo)", request=MemberCardRevokeSerializer,
                   responses={200: MemberCardSerializer, **ERRORS})
    def post(self, request, pk):
        card = _card_for(request.user, rbac.Action.MANAGE_MEMBER_CARDS, pk)
        serializer = MemberCardRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = member_card_services.revoke_card(request.user, card, reason=serializer.validated_data.get("reason") or "revoked")
        return Response(MemberCardSerializer(card).data)


def _pdf_response(pdf, filename):
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class MemberCardPrintView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Print one card (CR80 PDF)", request=None,
                   responses={(200, "application/pdf"): OpenApiTypes.BINARY, **ERRORS})
    def post(self, request, pk):
        card = _card_for(request.user, rbac.Action.MANAGE_MEMBER_CARDS, pk)
        if not card.is_active:
            raise PermissionDenied("A revoked card cannot be printed.")
        template = member_card_templates.normalize_template(dict(member_card_templates.template_for(card.makerspace), page="cr80"))
        pdf = member_card_printing.render_cards_pdf(template, [snapshot_for(card)], title=f"Member card {card.card_number}")
        member_card_services.record_print(request.user, [card])
        return _pdf_response(pdf, f"member-card-{card.card_number:05d}.pdf")


class MemberCardSheetView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Print a sheet of cards", request=MemberCardPrintSerializer,
                   responses={(200, "application/pdf"): OpenApiTypes.BINARY, **ERRORS})
    def post(self, request, makerspace_id):
        makerspace = _makerspace_for(request.user, rbac.Action.MANAGE_MEMBER_CARDS, makerspace_id)
        serializer = MemberCardPrintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cards = MemberCard.objects.filter(makerspace=makerspace, revoked_at__isnull=True, membership__isnull=False).select_related("makerspace", "membership__assigned_role")
        ids = serializer.validated_data.get("card_ids")
        if ids:
            cards = cards.filter(pk__in=ids)
        cards = list(cards.order_by("card_number")[:200])
        template = member_card_templates.template_for(makerspace)
        if serializer.validated_data.get("preset") == "single":
            template = member_card_templates.normalize_template(dict(template, page="cr80"))
        pdf = member_card_printing.render_cards_pdf(template, [snapshot_for(card) for card in cards], title="Member cards")
        member_card_services.record_print(request.user, cards)
        return _pdf_response(pdf, "member-cards.pdf")


class MemberCardResolveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Resolve a scanned member card to minimal identity",
                   request=MemberCardResolveSerializer, responses={200: MemberCardResolveResultSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        makerspace = _makerspace_for(request.user, rbac.Action.SCAN_MEMBER_CARDS, makerspace_id)
        serializer = MemberCardResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = member_card_services.resolve(request.user, makerspace, serializer.validated_data["payload"])
        except Http404:
            raise
        return Response(result)


class MemberCardTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=[TAG], summary="Read the card layout template", request=None,
                   responses={200: MemberCardTemplateSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        makerspace = _makerspace_for(request.user, rbac.Action.SCAN_MEMBER_CARDS, makerspace_id)
        return Response(member_card_templates.template_for(makerspace))

    @extend_schema(tags=[TAG], summary="Replace the card layout template", request=MemberCardTemplateSerializer,
                   responses={200: MemberCardTemplateSerializer, **ERRORS})
    def put(self, request, makerspace_id):
        makerspace = _makerspace_for(request.user, rbac.Action.MANAGE_MEMBER_CARDS, makerspace_id)
        serializer = MemberCardTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = member_card_templates.save_template(makerspace, serializer.validated_data)
        audit.record(request.user, "member_card.template_updated", makerspace=makerspace, target=makerspace, meta={"version": template["version"]})
        return Response(template)
