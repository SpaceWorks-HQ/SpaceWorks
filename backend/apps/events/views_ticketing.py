from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit.services import record
from apps.events.models import EventCategory, EventPromoCode
from apps.events.promos import create_promo, revoke_promo
from apps.events.invites import require_feature
from apps.events.ticketing import create_ticket
from apps.events.views_admin_event_detail import _manageable_event, _visible_makerspace
from apps.events.views_invites import ERRORS, PAGE_PARAMETERS, paginated, manageable_event_code
from apps.events.serializers_admin import EmptyActionSerializer
from apps.events.serializers_ticketing import (
    TicketInputSerializer, TicketSerializer, TicketListSerializer,
    PromoInputSerializer, PromoSerializer, PromoListSerializer,
    CategoryInputSerializer, CategorySerializer, CategoryListSerializer,
)


class EventTicketListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=None, parameters=PAGE_PARAMETERS, responses={200: TicketListSerializer, **ERRORS})
    def get(self, request, pk):
        event = _manageable_event(request.user, pk)
        require_feature(event, "events.ticket_types")
        return paginated(request, event.ticket_types.order_by("id"), TicketSerializer)

    @extend_schema(tags=["Admin events"], request=TicketInputSerializer, responses={201: TicketSerializer, **ERRORS})
    def post(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = TicketInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = create_ticket(event, actor=request.user, **serializer.validated_data)
        return Response(TicketSerializer(ticket).data, status=201)


class EventPromoListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=None, parameters=PAGE_PARAMETERS, responses={200: PromoListSerializer, **ERRORS})
    def get(self, request, pk):
        event = _manageable_event(request.user, pk)
        require_feature(event, "events.promo_codes")
        return paginated(request, event.promo_codes.order_by("id"), PromoSerializer)

    @extend_schema(tags=["Admin events"], request=PromoInputSerializer, responses={201: PromoSerializer, **ERRORS})
    def post(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = PromoInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        promo, code = create_promo(event, actor=request.user, **serializer.validated_data)
        return Response({**PromoSerializer(promo).data, "code": code}, status=201)


class EventPromoRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=EmptyActionSerializer, responses={200: PromoSerializer, **ERRORS})
    def post(self, request, pk):
        promo = manageable_event_code(request.user, EventPromoCode.objects.all(), pk)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(PromoSerializer(revoke_promo(promo, actor=request.user)).data)


class EventCategoryListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=None, parameters=PAGE_PARAMETERS, responses={200: CategoryListSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = _visible_makerspace(request.user, makerspace_id)
        rows = rbac.scope_by_action(request.user, rbac.Action.MANAGE_EVENTS, EventCategory.objects.all()).filter(makerspace=space)
        return paginated(request, rows, CategorySerializer)

    @extend_schema(tags=["Admin events"], request=CategoryInputSerializer, responses={201: CategorySerializer, **ERRORS})
    @transaction.atomic
    def post(self, request, makerspace_id):
        from apps.makerspaces.guards import require_module_locked
        space = _visible_makerspace(request.user, makerspace_id)
        require_module_locked(space, "events")
        serializer = CategoryInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if EventCategory.objects.filter(makerspace=space, slug=serializer.validated_data["slug"]).exists():
            raise ValidationError({"slug": "Category already exists."})
        category = EventCategory.objects.create(makerspace=space, **serializer.validated_data)
        record(request.user, "event.category_created", makerspace=space, target=category)
        return Response(CategorySerializer(category).data, status=201)
