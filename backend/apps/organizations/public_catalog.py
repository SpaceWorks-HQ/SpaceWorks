from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from apps.events.models import Event, EventRegistration
from apps.events.organizer_models import EventOrganizer
from apps.makerspaces.servability import servable_q
from apps.separability.registry import runtime_active


def public_events_for(organization):
    if not runtime_active("events"):
        return Event.objects.none()
    return (
        Event.objects.filter(
            organizers__organization=organization,
            makerspace__hidden_from_central_directory=False,
            makerspace__enabled_modules__contains=["events"],
            is_public=True,
            status=Event.Status.PUBLISHED,
            ends_at__gte=timezone.now(),
        )
        .filter(servable_q("makerspace"))
        .select_related("makerspace")
        .prefetch_related(
            Prefetch(
                "organizers",
                queryset=EventOrganizer.objects.select_related("organization"),
            )
        )
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
        .distinct()
        .order_by("starts_at", "id")
    )
