from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.events.serializers_admin import (
    EmptyActionSerializer,
    EventAdminSerializer,
    EventListResponseSerializer,
    EventRegistrationAdminSerializer,
    EventEligibleMemberSerializer,
    EventRegistrationListResponseSerializer,
    EventStaffRegistrationSerializer,
    EventWriteSerializer,
)
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.events import services
from apps.events.models import Event, EventRegistration
from apps.events.organizer_authority import can_manage_event, organizer_event_q
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.payments.models import Payment


EVENT_VALIDATION_ERROR_SCHEMA = {'type': 'object', 'additionalProperties': {}}
EVENT_ERROR_400 = OpenApiResponse(
    EVENT_VALIDATION_ERROR_SCHEMA,
    description='Invalid event details.',
)
EVENT_ERROR_409 = OpenApiResponse(
    ErrorSerializer,
    description='Event state or capacity conflict.',
)


class _EventPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class _RegistrationPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


def _visible_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_EVENTS,
            Makerspace.objects.all(),
            field='id',
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, 'events')
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _manageable_event(actor, pk):
    venue_scoped = rbac.scope_by_visibility_or_action(
        actor,
        rbac.Action.MANAGE_EVENTS,
        Event.objects.all(),
        field='makerspace_id',
    )
    event = get_object_or_404(
        Event.objects.select_related('makerspace')
        .prefetch_related('organizers__organization')
        .filter(
            Q(pk__in=venue_scoped.values('pk'))
            | organizer_event_q(actor)
        )
        .distinct(),
        pk=pk,
    )
    require_module(event.makerspace, 'events')
    if not can_manage_event(actor, event):
        raise PermissionDenied()
    return event


def _manageable_registration(actor, pk):
    venue_scoped = rbac.scope_by_visibility_or_action(
        actor,
        rbac.Action.MANAGE_EVENTS,
        EventRegistration.objects.all(),
        field='event__makerspace_id',
    )
    registration = get_object_or_404(
        EventRegistration.objects.select_related('event__makerspace')
        .filter(
            Q(pk__in=venue_scoped.values('pk'))
            | organizer_event_q(actor, event_prefix='event__')
        )
        .distinct(),
        pk=pk,
    )
    require_module(registration.event.makerspace, 'events')
    if not can_manage_event(actor, registration.event):
        raise PermissionDenied()
    return registration


def _annotate_registration_counts(queryset):
    return queryset.annotate(
        **{
            f'{value}_count': Count(
                'registrations',
                filter=Q(registrations__status=value),
            )
            for value in EventRegistration.Status.values
        }
    )


def _paginated_response(paginator, page, serializer):
    return Response(
        {
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
            'results': serializer(page, many=True).data,
        }
    )


def _validate_empty_action(request):
    serializer = EmptyActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)


class EventListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin events'],
        summary='List events in a makerspace',
        request=None,
        responses={200: EventListResponseSerializer},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        queryset = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            Event.objects.filter(makerspace=makerspace),
            field='makerspace_id',
        )
        queryset = (
            _annotate_registration_counts(queryset)
            .prefetch_related('organizers__organization')
            .order_by('starts_at', 'id')
        )
        paginator = _EventPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return _paginated_response(paginator, page, EventAdminSerializer)

    @extend_schema(
        tags=['Admin events'],
        summary='Create a draft event',
        request=EventWriteSerializer,
        responses={
            201: EventAdminSerializer,
            400: EVENT_ERROR_400,
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        serializer = EventWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = services.create_event(
            makerspace=makerspace,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            EventAdminSerializer(event).data,
            status=status.HTTP_201_CREATED,
        )


class EventDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin events'],
        summary='Retrieve an event',
        request=None,
        responses={200: EventAdminSerializer},
    )
    def get(self, request, pk, *args, **kwargs):
        return Response(EventAdminSerializer(_manageable_event(request.user, pk)).data)

    @extend_schema(
        tags=['Admin events'],
        summary='Update an event',
        request=EventWriteSerializer,
        responses={
            200: EventAdminSerializer,
            400: EVENT_ERROR_400,
            409: EVENT_ERROR_409,
        },
    )
    def patch(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = EventWriteSerializer(event, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        event = services.update_event(
            event,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(EventAdminSerializer(event).data)


class _EventActionView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def execute(self, request, pk):
        event = _manageable_event(request.user, pk)
        _validate_empty_action(request)
        event = self.operation(event, actor=request.user)
        return Response(EventAdminSerializer(event).data)


class EventPublishView(_EventActionView):
    operation = staticmethod(services.publish)

    @extend_schema(
        tags=['Admin events'],
        summary='Publish an event',
        request=EmptyActionSerializer,
        responses={200: EventAdminSerializer, 400: EVENT_ERROR_400, 409: EVENT_ERROR_409},
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class EventCancelView(_EventActionView):
    operation = staticmethod(services.cancel)

    @extend_schema(
        tags=['Admin events'],
        summary='Cancel an event',
        request=EmptyActionSerializer,
        responses={200: EventAdminSerializer, 409: EVENT_ERROR_409},
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class EventCompleteView(_EventActionView):
    operation = staticmethod(services.complete)

    @extend_schema(
        tags=['Admin events'],
        summary='Complete an event',
        request=EmptyActionSerializer,
        responses={200: EventAdminSerializer, 409: EVENT_ERROR_409},
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)

