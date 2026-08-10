"""Keep member-event provenance in the events app.

This helper disappears with an events tombstone and centralizes the predicate so a
later move to a durable provenance column changes one body instead of several call
sites. It deliberately never matches email: a nullable member plus a shared address
could otherwise attach one person's attendance to another person's profile.
"""


def registrations_for_space(makerspace, user):
    """Every registration this member holds in this space."""
    from apps.events.models import EventRegistration

    return EventRegistration.objects.filter(
        event__makerspace=makerspace, member=user
    )
