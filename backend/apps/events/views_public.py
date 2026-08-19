from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.events import services
from apps.events.exceptions import DuplicateRegistration
from apps.events.models import Event, EventRegistration
from apps.events.serializers_public import (
    PublicEventRegistrationInputSerializer,
    PublicEventRegistrationResponseSerializer,
    PublicEventSerializer,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.presence.guard import require_active_member


LOOSE_ERROR_SCHEMA = {'type': 'object', 'additionalProperties': {}}

PUBLIC_EVENT_ERRORS = {
    400: OpenApiResponse(LOOSE_ERROR_SCHEMA, description='Invalid request.'),
    404: OpenApiResponse(LOOSE_ERROR_SCHEMA, description='Event not found.'),
    429: OpenApiResponse(LOOSE_ERROR_SCHEMA, description='Rate limit exceeded.'),
}
PUBLIC_EVENT_REGISTRATION_ERRORS = {
    **PUBLIC_EVENT_ERRORS,
    401: OpenApiResponse(ErrorSerializer, description='Authentication is required.'),
    403: OpenApiResponse(ErrorSerializer, description='Active membership and current waiver acceptance are required.'),
    409: OpenApiResponse(ErrorSerializer, description='Event state conflict.'),
}


def _public_events(makerspace):
    return Event.objects.filter(
        makerspace=makerspace,
        is_public=True,
        status=Event.Status.PUBLISHED,
        ends_at__gte=timezone.now(),
    )


class PublicEventListView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'public_read'

    @extend_schema(
        tags=['Public events'],
        auth=[],
        request=None,
        responses={200: PublicEventSerializer(many=True), **PUBLIC_EVENT_ERRORS},
    )
    def get(self, request, makerspace_slug):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module(makerspace, 'events')
        events = (
            _public_events(makerspace)
            .prefetch_related('organizers__organization')
            .annotate(
                confirmed_count=Count(
                    'registrations',
                    filter=Q(
                        registrations__status__in=(
                            EventRegistration.Status.REGISTERED,
                            EventRegistration.Status.ATTENDED,
                        )
                    ),
                )
            )
            .order_by('starts_at', 'id')
        )
        return Response(PublicEventSerializer(events, many=True).data)


class PublicEventRegistrationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'event_register'

    @extend_schema(
        tags=['Public events'],
        request=PublicEventRegistrationInputSerializer,
        responses={
            201: PublicEventRegistrationResponseSerializer,
            **PUBLIC_EVENT_REGISTRATION_ERRORS,
        },
    )
    def post(self, request, makerspace_slug, public_token):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module(makerspace, 'events')
        event = get_object_or_404(
            _public_events(makerspace),
            public_token=public_token,
        )
        # Membership and waiver, but deliberately NOT an open presence session: signing
        # up is planning to attend, and a member registering in advance from home cannot
        # be checked in. Physical attendance is established by the staff-scanned QR
        # check-in instead, which is stronger evidence than a self-declared session.
        require_active_member(request.user, makerspace)

        website = request.data.get('website')
        if website and str(website).strip():
            return Response(
                {'status': EventRegistration.Status.REGISTERED},
                status=status.HTTP_201_CREATED,
            )

        serializer = PublicEventRegistrationInputSerializer(
            data=request.data,
            context={'event': event},
        )
        serializer.is_valid(raise_exception=True)
        registration_data = dict(serializer.validated_data)
        registration_data['custom_answers'] = request.data.get('custom_answers')
        try:
            registration = services.register(
                event,
                member=request.user,
                actor=request.user,
                **registration_data,
            )
        except DuplicateRegistration as exc:
            return Response(
                {'status': exc.fresh_status},
                status=status.HTTP_201_CREATED,
            )
        return Response(
            PublicEventRegistrationResponseSerializer(registration).data,
            status=status.HTTP_201_CREATED,
        )
