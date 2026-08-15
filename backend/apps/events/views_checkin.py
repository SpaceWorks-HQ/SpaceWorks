from uuid import UUID

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_payment_summary import scoped_payment_context
from apps.boxes.qr_render import render_qr_label_svg
from apps.events.member_history import registrations_for_space
from apps.events.models import Event, EventRegistration
from apps.events.serializers_checkin import (
    EventCheckInResolveRequestSerializer,
    EventCheckInResolveResponseSerializer,
)
from apps.events.throttles import EventCheckInResolveThrottle
from apps.events.views_admin import _manageable_event
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.waiver_state import acceptance_on_file_q
from apps.payments.models import Payment
from apps.presence.guard import MemberPresenceRequired


# A check-in is only meaningful while the event is still happening or has happened. Shared
# by the QR route and the member-activity token so the two cannot disagree about whether a
# code is usable.
CHECKABLE_EVENT_STATUSES = (Event.Status.PUBLISHED, Event.Status.COMPLETED)


def host_waiver_state(registration):
    """Which waiver evidence exists for this registration, across BOTH locations.

    A visitor's acceptance is stamped on the registration; a host member's lives on their
    MakerspaceMembership. Reading only the first is why every host member was told to take
    a waiver at the desk. Deliberately NOT compared against the waiver's current version:
    a host revising its terms must not retroactively invalidate an acceptance somebody
    already gave, the same rule the QR gate follows.
    """
    if not MakerspaceWaiver.objects.filter(
        makerspace_id=registration.event.makerspace_id,
        is_active=True,
    ).exists():
        return "not_required"

    if registration.host_waiver_id:
        return "on_file"

    if registration.member_id and MakerspaceMembership.objects.filter(
        user_id=registration.member_id,
        makerspace_id=registration.event.makerspace_id,
    ).filter(acceptance_on_file_q()).exists():
        return "on_file"

    return "missing"


class EventCheckInResolveView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [EventCheckInResolveThrottle]

    @extend_schema(
        tags=["Admin events"],
        summary="Resolve an event check-in token",
        request=EventCheckInResolveRequestSerializer,
        responses={
            200: EventCheckInResolveResponseSerializer,
            403: OpenApiResponse(ErrorSerializer, description="Event access denied."),
            404: OpenApiResponse(ErrorSerializer, description="Registration not found."),
            429: OpenApiResponse(ErrorSerializer, description="Request rate limit exceeded."),
        },
    )
    def post(self, request, pk, *args, **kwargs):
        event = _manageable_event(request.user, pk)
        try:
            token = UUID(str(request.data["checkin_token"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise NotFound() from None

        registration = (
            EventRegistration.objects.filter(
                event=event,
                checkin_token=token,
            )
            .select_related("event")
            .first()
        )
        if registration is None:
            raise NotFound()

        payment_context = scoped_payment_context(
            request.user,
            rbac.Action.MANAGE_EVENTS,
            Payment.SubjectType.EVENT_REGISTRATION,
            [registration.pk],
        )
        payment = payment_context["payments_by_subject_id"].get(registration.pk)
        payload = {
            "registration_id": registration.pk,
            "name": registration.name,
            "status": registration.status,
            "payment_status": payment.status if payment is not None else None,
            # Reported, never enforced. A visitor with nothing on file is exactly who the
            # host wants to hand a waiver to at the desk; refusing them entry is not this
            # endpoint's job, the same way it reports payment state without blocking.
            "host_waiver_state": host_waiver_state(registration),
            "event_status": registration.event.status,
            # Mirrors mark_attended's own precondition so the scanner does not offer a
            # button whose request can only return 409.
            "confirmable": (
                registration.status == EventRegistration.Status.REGISTERED
                and registration.event.status in CHECKABLE_EVENT_STATUSES
            ),
        }
        response = Response(EventCheckInResolveResponseSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response


class EventCheckInQrView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member activity"],
        summary="Render the caller's event check-in QR code",
        request=None,
        responses={
            # Keyed with the media type: without it drf-spectacular documents this as
            # application/json and a generated client would try to parse the SVG as JSON.
            (200, "image/svg+xml"): OpenApiResponse(
                OpenApiTypes.BINARY,
                description="Check-in QR code as SVG.",
            ),
            403: OpenApiResponse(
                ErrorSerializer,
                description="An active membership is required.",
            ),
            404: OpenApiResponse(ErrorSerializer, description="Registration not found."),
        },
    )
    def get(self, request, makerspace_id, pk, *args, **kwargs):
        membership = active_membership(request.user, makerspace_id)
        if membership is None:
            raise MemberPresenceRequired()
        makerspace = membership.makerspace
        require_module(makerspace, "events")

        registration = (
            registrations_for_space(makerspace, request.user)
            .filter(
                pk=pk,
                member=request.user,
                status=EventRegistration.Status.REGISTERED,
                # The EVENT's status matters too, not just the registration's.
                # `services.cancel()` changes only `Event.status` and leaves every
                # registration REGISTERED, so without this a member keeps a QR for a
                # cancelled event -- one `mark_attended` will always refuse, and which the
                # staff scanner is not even offered for. An admission code that cannot
                # admit anyone is worse than none.
                event__status__in=CHECKABLE_EVENT_STATUSES,
            )
            .select_related("event")
            .first()
        )
        if registration is None:
            raise NotFound()

        # A collaborative registration must carry SOME recorded host-waiver acceptance before
        # it yields an admission code. Provenance differing from the host is what marks a
        # visitor; the host's own members carry their acceptance on their membership.
        #
        # Deliberately NOT gated on the CURRENT version. A host revising its waiver after
        # someone registered would then silently void a legitimate member's code and turn them
        # away at a door they signed up for, over text they never had the chance to read --
        # the same failure the never-block rule prevents for payments. What this closes is the
        # row with NO acceptance at all, and the member can repair it themselves by
        # re-submitting registration, which stamps the current waiver.
        if (
            registration.registered_via_makerspace_id
            and registration.registered_via_makerspace_id != registration.event.makerspace_id
            and registration.host_waiver_id is None
            and MakerspaceWaiver.objects.filter(
                makerspace_id=registration.event.makerspace_id, is_active=True,
            ).exists()
        ):
            raise NotFound()

        title = registration.event.title
        label = title if len(title) <= 40 else f"{title[:37].rstrip()}..."
        response = HttpResponse(
            render_qr_label_svg(str(registration.checkin_token), label=label),
            content_type="image/svg+xml",
        )
        response["Cache-Control"] = "private, no-store"
        return response
