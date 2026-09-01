from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.events import services
from apps.events.models import EventRegistration
from apps.events.serializers_admin import (
    EmptyActionSerializer,
    EventEligibleMemberSerializer,
    EventRegistrationAdminSerializer,
    EventRegistrationListResponseSerializer,
    EventStaffRegistrationSerializer,
)
from apps.events.views_admin_events import (
    EVENT_ERROR_409,
    _manageable_event,
    _manageable_registration,
    _paginated_response,
    _RegistrationPagination,
    _validate_empty_action,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment


REGISTRATION_ACTION_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description='Unexpected request body.'),
    401: OpenApiResponse(ErrorSerializer, description='Authentication is required.'),
    403: OpenApiResponse(ErrorSerializer, description='Event management is required.'),
    404: OpenApiResponse(ErrorSerializer, description='Registration not found.'),
    409: EVENT_ERROR_409,
}


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


class _RegistrationActionView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def execute(self, request, pk):
        registration = _manageable_registration(request.user, pk)
        _validate_empty_action(request)
        registration = self.operation(registration, actor=request.user)
        context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            Payment.SubjectType.EVENT_REGISTRATION,
            [registration.pk],
        )
        return Response(
            EventRegistrationAdminSerializer(registration, context=context).data
        )


class EventRegistrationApproveView(_RegistrationActionView):
    operation = staticmethod(services.approve_registration)

    @extend_schema(
        tags=['Admin events'],
        summary='Approve a pending event registration',
        request=EmptyActionSerializer,
        responses={200: EventRegistrationAdminSerializer, **REGISTRATION_ACTION_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class EventRegistrationRejectView(_RegistrationActionView):
    operation = staticmethod(services.reject_registration)

    @extend_schema(
        tags=['Admin events'],
        summary='Reject a pending or waitlisted event registration',
        request=EmptyActionSerializer,
        responses={200: EventRegistrationAdminSerializer, **REGISTRATION_ACTION_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


class EventRegistrationPromoteView(_RegistrationActionView):
    operation = staticmethod(services.promote_registration)

    @extend_schema(
        tags=['Admin events'],
        summary='Manually promote an approved waitlisted registration',
        request=EmptyActionSerializer,
        responses={200: EventRegistrationAdminSerializer, **REGISTRATION_ACTION_ERRORS},
    )
    def post(self, request, pk, *args, **kwargs):
        return self.execute(request, pk)


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
