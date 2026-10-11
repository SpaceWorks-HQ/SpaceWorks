"""Bulk ticket facts for event lists, with the same audience rules as checkout."""

from django.db.models import Count, F, Prefetch, Q

from apps.events.capacity import CONFIRMED_STATUSES
from apps.events.models import EventTicketType
from apps.makerspaces.models import MakerspaceMembership


def with_public_tickets(events):
    tickets = EventTicketType.objects.filter(is_active=True).annotate(
        confirmed_count=Count(
            "eventregistration", filter=Q(
                eventregistration__status__in=CONFIRMED_STATUSES,
                eventregistration__event_id=F("event_id"),
            ),
        ),
    )
    return events.prefetch_related(Prefetch(
        "ticket_types", queryset=tickets, to_attr="public_ticket_rows",
    ))


def ticket_membership_ids(user, events):
    """Resolve the audience once across all hosts, never once per event."""
    if not user or not user.is_authenticated or not user.is_active or user.access_status != "active":
        return set()
    return set(MakerspaceMembership.objects.filter(
        user=user, status="active", makerspace_id__in={event.makerspace_id for event in events},
    ).values_list("makerspace_id", flat=True))
