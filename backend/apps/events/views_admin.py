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
        rbac.scope_by_makerspace(
            actor,
            Makerspace.objects.all(),
            makerspace_field='id',
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, 'events')
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _manageable_event(actor, pk):
    event = get_object_or_404(
        rbac.scope_by_makerspace(
            actor,
            Event.objects.select_related('makerspace'),
            makerspace_field='makerspace_id',
        ),
        pk=pk,
    )
    require_module(event.makerspace, 'events')
    if not rbac.can(actor, rbac.Action.MANAGE_EVENTS, event.makerspace_id):
        raise PermissionDenied()
    return event


def _manageable_registration(actor, pk):
    registration = get_object_or_404(
        rbac.scope_by_makerspace(
            actor,
            EventRegistration.objects.select_related('event__makerspace'),
            makerspace_field='event__makerspace_id',
        ),
        pk=pk,
    )
    require_module(registration.event.makerspace, 'events')
    if not rbac.can(
        actor,
        rbac.Action.MANAGE_EVENTS,
        registration.event.makerspace_id,
    ):
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
        queryset = _annotate_registration_counts(queryset).order_by('starts_at', 'id')
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


class EventRegistrationListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin events'],
        summary='List event registrations',
        request=None,
        responses={200: EventRegistrationListResponseSerializer},
    )
    def get(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        queryset = EventRegistration.objects.filter(event=event).order_by('created_at', 'id')
        paginator = _RegistrationPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            Payment.SubjectType.EVENT_REGISTRATION,
            [registration.pk for registration in page],
        )
        return _paginated_response(
            paginator,
            page,
            lambda rows, many: EventRegistrationAdminSerializer(
                rows,
                many=many,
                context=context,
            ),
        )

    # Registering someone from the console goes through the SAME
    # `services_registration.register` as public self-registration: capacity,
    # waitlisting, duplicate handling, the custom form, the write fence and the
    # registration charge are one implementation, as the request-workflow rule requires
    # of every state machine here.
    #
    # Takes a `member_id` rather than free-text contact fields. Registering someone
    # means naming a real person, and a person with no account is given one at the
    # counter (`walk_in_services`) first — so there is one identity path, instead of the
    # events surface minting half-identified attendees of its own.

    @extend_schema(
        tags=['Admin events'],
        summary='Register a member for an event',
        request=EventStaffRegistrationSerializer,
        responses={
            201: EventRegistrationAdminSerializer,
            400: OpenApiResponse(ErrorSerializer, description='Invalid registration.'),
            409: EVENT_ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        serializer = EventStaffRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = get_object_or_404(
            MakerspaceMembership.objects.select_related('user').filter(
                makerspace=event.makerspace,
                user_id=serializer.validated_data['member_id'],
                status='active',
                user__is_active=True,
                # Account standing, not just the membership row: a restricted or
                # suspended account is blocked everywhere else and must be blocked here
                # too, or the console becomes the way around an access restriction.
                user__access_status=User.AccessStatus.ACTIVE,
            )
        )
        registration = services.register(
            event,
            member=membership.user,
            phone=serializer.validated_data.get('phone', ''),
            email=serializer.validated_data.get('email', ''),
            custom_answers=serializer.validated_data.get('custom_answers'),
            actor=request.user,
            staff_registration=True,
        )
        context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            Payment.SubjectType.EVENT_REGISTRATION,
            [registration.pk],
        )
        return Response(
            EventRegistrationAdminSerializer(registration, context=context).data,
            status=status.HTTP_201_CREATED,
        )


class EventRegistrationMarkAttendedView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin events'],
        summary='Mark an event registration attended',
        request=EmptyActionSerializer,
        responses={200: EventRegistrationAdminSerializer, 409: EVENT_ERROR_409},
    )
    def post(self, request, pk, *args, **kwargs):
        registration = _manageable_registration(request.user, pk)
        _validate_empty_action(request)
        registration = services.mark_attended(registration, actor=request.user)
        context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            Payment.SubjectType.EVENT_REGISTRATION,
            [registration.pk],
        )
        return Response(
            EventRegistrationAdminSerializer(
                registration,
                context=context,
            ).data
        )


class EventEligibleMemberListView(APIView):
    """The roster the staff registration picker reads.

    Hung off the EVENT rather than the makerspace, so it inherits `_manageable_event`
    and introduces no new authority question: whoever may manage this event may see who
    they can register for it. A separate makerspace-level member list would have needed
    its own permission answer, and the obvious candidates were all wrong — the
    direct-loan roster is gated on `ISSUE_DIRECT_LOAN` plus a self-checkout feature an
    events manager need not hold, and the full membership list is `MANAGE_MAKERSPACE`.

    Already-registered members are excluded: offering someone the picker can only reject
    as a duplicate is an error the interface should not have made available.
    """

    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin events'],
        summary='List members who can be registered for an event',
        request=None,
        responses={200: EventEligibleMemberSerializer(many=True)},
    )
    def get(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        registered = EventRegistration.objects.filter(event=event).exclude(
            status=EventRegistration.Status.CANCELLED
        ).values_list('member_id', flat=True)
        memberships = MakerspaceMembership.objects.select_related('user').filter(
            makerspace=event.makerspace, status='active', user__is_active=True,
            user__access_status=User.AccessStatus.ACTIVE,
        ).exclude(user_id__in=[value for value in registered if value]).order_by(
            'user__display_name', 'user__username'
        )
        return Response(
            EventEligibleMemberSerializer(
                [
                    {
                        'member_id': membership.user_id,
                        'display_name': (
                            membership.user.display_name or membership.user.username
                        ),
                    }
                    for membership in memberships
                ],
                many=True,
            ).data
        )
