from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.events import services
from apps.events.exceptions import DuplicateRegistration
from apps.events.models import Event, EventCollaborator, EventRegistration
from apps.events.serializers_collaborators import (
    CollaborativeEventRegistrationInputSerializer,
    CollaborativeEventSerializer,
)
from apps.events.serializers_public import PublicEventRegistrationResponseSerializer
from apps.events.throttles import CollaborativeRegistrationThrottle
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module, require_module_locked
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_q, servable_queryset
from apps.presence.guard import MemberPresenceRequired, require_active_member


MEMBER_EVENT_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid event request."),
    403: OpenApiResponse(ErrorSerializer, description="Active membership is required."),
    404: OpenApiResponse(ErrorSerializer, description="Collaborative event not found."),
}


def _active_membership(request, makerspace_id):
    """Membership AND the collaborating space's current waiver.

    `active_membership()` alone does not check the waiver, and collaboration is meant to
    relax exactly one condition -- `is_public` -- so the liability factor must survive. This
    is the same guard the ordinary member registration path uses
    (`views_public.PublicEventRegistrationView`), pointed at the COLLABORATOR: the visiting
    member is one of its members, and it is the space that holds their acceptance.
    """
    membership = active_membership(request.user, makerspace_id)
    if membership is None:
        raise MemberPresenceRequired()
    require_module(membership.makerspace, "events")
    require_active_member(request.user, membership.makerspace)
    return membership


def _collaborative_events(makerspace):
    """Events this space's members may register for through the member surface.

    TWO arms, and the host arm is not an afterthought: without it a partner's members could
    register for A's members-only event while A's OWN members could not, since the public
    listing hides a non-public event and this queryset would exclude events A hosts. The
    asymmetry would be absurd -- the space that created the event being the one space unable
    to see it.
    """
    return servable_queryset(Event.objects.filter(
        Q(makerspace=makerspace)
        | Q(
            collaborators__makerspace=makerspace,
            collaborators__status=EventCollaborator.Status.ACCEPTED,
        ) & servable_q("collaborators__makerspace"),
        makerspace__enabled_modules__contains=["events"],
        status=Event.Status.PUBLISHED,
        ends_at__gte=timezone.now(),
    ), relation="makerspace").distinct()


class MemberCollaborativeEventListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Member events"],
        summary="List events hosted by accepted collaborators",
        request=None,
        responses={
            200: CollaborativeEventSerializer(many=True),
            **MEMBER_EVENT_ERRORS,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        membership = _active_membership(request, makerspace_id)
        events = (
            _collaborative_events(membership.makerspace)
            .select_related("makerspace", "series")
            .prefetch_related("organizers__organization")
            .annotate(
                confirmed_count=Count(
                    "registrations",
                    filter=Q(
                        registrations__status__in=(
                            EventRegistration.Status.REGISTERED,
                            EventRegistration.Status.ATTENDED,
                        )
                    ),
                )
            )
            .order_by("starts_at", "id")
        )
        events = list(events)
        # One query for every host's active waiver, instead of one per event.
        active_waivers = {
            waiver.makerspace_id: waiver
            for waiver in MakerspaceWaiver.objects.filter(
                makerspace_id__in={event.makerspace_id for event in events},
                is_active=True,
            )
        }
        return Response(
            CollaborativeEventSerializer(
                events, many=True, context={"active_host_waivers": active_waivers},
            ).data
        )


def _stamp_host_waiver(registration, waiver, *, actor, via, event):
    """Record the acceptance and audit it, or do nothing if it is already current.

    Shared by the create path and the idempotent-retry path deliberately. Stamping in only
    one of them is how a pre-existing registration -- including every row written before this
    column existed -- keeps a working check-in QR while holding no acceptance at all, with no
    way for the member to ever correct it by retrying.
    """
    if waiver is None:
        return
    if (
        registration.host_waiver_id == waiver.pk
        and registration.host_waiver_version_accepted == waiver.version
    ):
        return
    registration.host_waiver = waiver
    registration.host_waiver_accepted_at = timezone.now()
    registration.host_waiver_version_accepted = waiver.version
    registration.save(update_fields=[
        "host_waiver", "host_waiver_accepted_at", "host_waiver_version_accepted",
    ])
    # `register()` emits `event.registration_created` before these fields exist, and it
    # carries only the registration id and status. The acceptance is evidence that a named
    # person agreed to specific terms, and a later purge clears the columns holding it -- the
    # append-only log is then the only place it survives. The waiver ID and VERSION go in;
    # the body never does, or the whole document is copied into an undeletable store on
    # every registration.
    audit.record(
        actor,
        "event.host_waiver_accepted",
        makerspace=event.makerspace,
        target=registration,
        meta={
            "registration_id": registration.pk,
            "host_waiver_id": waiver.pk,
            "host_waiver_version": waiver.version,
            "via_makerspace_id": via.pk,
        },
    )


class MemberCollaborativeEventRegistrationView(APIView):
    permission_classes = [IsAuthenticated]
    # Scope selection lives in the throttle itself -- see CollaborativeRegistrationThrottle
    # for why a repair retry must not share the create budget, and why a CANCELLED row is
    # not a retry.
    throttle_classes = [CollaborativeRegistrationThrottle]

    @extend_schema(
        tags=["Member events"],
        summary="Register for a collaborative event",
        request=CollaborativeEventRegistrationInputSerializer,
        responses={
            201: PublicEventRegistrationResponseSerializer,
            **MEMBER_EVENT_ERRORS,
            409: OpenApiResponse(ErrorSerializer, description="Event state conflict."),
            # Registration only -- the list view carries no throttle.
            429: OpenApiResponse(ErrorSerializer, description="Rate limit exceeded."),
        },
    )
    def post(self, request, makerspace_id, pk, *args, **kwargs):
        membership = _active_membership(request, makerspace_id)
        event = get_object_or_404(
            _collaborative_events(membership.makerspace).select_related("makerspace"),
            pk=pk,
        )
        serializer = CollaborativeEventRegistrationInputSerializer(
            data=request.data,
            context={"event": event},
        )
        serializer.is_valid(raise_exception=True)
        registration_data = serializer.validated_data.copy()
        submitted_waiver_id = registration_data.pop("host_waiver_id", None)
        submitted_waiver_version = registration_data.pop("host_waiver_version", None)
        submitted_waiver_accepted = registration_data.pop("host_waiver_accepted", False)

        with transaction.atomic():
            locked_event = Event.objects.select_for_update().get(pk=event.pk)
            # The view's collaboration check is unlocked and can go stale. Re-read it
            # under the event lock used by every collaboration mutation before register()
            # takes its own nested locks, so removal cannot race registration creation.
            collaboration = servable_queryset(
                EventCollaborator.objects.filter(
                    event=locked_event,
                    makerspace=membership.makerspace,
                    status=EventCollaborator.Status.ACCEPTED,
                ),
                relation="makerspace",
            )
            collaboration = (
                collaboration
                .select_related("makerspace")
                .first()
            )
            if collaboration is None and locked_event.makerspace_id != membership.makerspace_id:
                raise NotFound()
            # The COLLABORATOR's module gate must be re-checked under ITS row lock too.
            # `register()` locks only the host, so an unlocked read here leaves the window
            # every `require_module_locked` call site exists to close: the partner
            # uninstalls `events` and purges it, and this insert then writes provenance
            # pointing at the partner *after* an irreversible purge cleared exactly those
            # rows. Event lock first, then makerspace, matching `publish()`.
            via = collaboration.makerspace if collaboration else membership.makerspace
            # Lock the host and the collaborator TOGETHER in primary-key order. Locking only
            # `via` here and letting `register()` take the host afterwards deadlocks on
            # reciprocal collaborations: an A-hosted event via B takes B then A, while a
            # B-hosted event via A takes A then B, and the two event locks are different rows
            # so Postgres has to abort one.
            list(
                Makerspace.objects.select_for_update()
                .filter(pk__in={locked_event.makerspace_id, via.pk})
                .order_by("pk")
            )
            require_module_locked(via.pk, "events")
            host_waiver = None
            # Host members already accepted this waiver through require_active_member;
            # recording or requiring the same agreement twice would be misleading.
            if locked_event.makerspace_id != membership.makerspace_id:
                # The host row lock makes this a current-version read: publishing a new
                # waiver takes the same lock, so a rendered superseded version cannot win.
                host_waiver = MakerspaceWaiver.objects.filter(
                    makerspace_id=locked_event.makerspace_id, is_active=True,
                ).first()
                if host_waiver and (
                    not submitted_waiver_accepted
                    or submitted_waiver_id != host_waiver.id
                    or submitted_waiver_version != host_waiver.version
                ):
                    raise ValidationError({
                        "host_waiver": "The current host waiver must be accepted."
                    })
            # And the membership + waiver, re-read under the collaborator's now-held row
            # lock. `_active_membership` ran unlocked at the top of the request, so a
            # revocation or a new waiver version committed since then would otherwise
            # still produce a registration -- eligibility has to be as transactional as
            # the module gate beside it.
            MakerspaceMembership.objects.select_for_update().filter(
                makerspace_id=via.pk, user=request.user,
            ).first()
            require_active_member(request.user, via)
            try:
                registration = services.register(
                    locked_event,
                    member=request.user,
                    actor=request.user,
                    collaborative=True,
                    via_makerspace=via,
                    **registration_data,
                )
                _stamp_host_waiver(
                    registration, host_waiver,
                    actor=request.user, via=via, event=locked_event,
                )
            except DuplicateRegistration:
                # A lost response or a double-submit must not report failure for a
                # registration that exists. Report the status of the row the caller ACTUALLY
                # owns, not `exc.fresh_status` -- that is the status a *new* registration
                # would receive, so once the event filled it would tell a confirmed member
                # they are waitlisted.
                owned_row = EventRegistration.objects.filter(
                    event=locked_event, member=request.user,
                ).first()
                if owned_row is not None:
                    # A retry is the member's only way to supply an acceptance their existing
                    # row never had -- every registration written before this column existed
                    # is in exactly that state, with a working QR and no recorded agreement.
                    _stamp_host_waiver(
                        owned_row, host_waiver,
                        actor=request.user, via=via, event=locked_event,
                    )
                return Response(
                    {"status": owned_row.status if owned_row else None},
                    status=status.HTTP_201_CREATED,
                )
        return Response(
            PublicEventRegistrationResponseSerializer(registration).data,
            status=status.HTTP_201_CREATED,
        )
