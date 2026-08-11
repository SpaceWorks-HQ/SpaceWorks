"""Which payments a member may see and pay through ONE makerspace's member area.

Written once and used by all three member payment surfaces (history, web checkout, native
intent) because they have to agree: a charge visible in history but unpayable at checkout,
or vice versa, is worse than either alone.

The problem this solves: a collaborative event is hosted by A, so `Payment` is created under
A (correctly -- ownership decides which Stripe account is charged). But a member of B
reaching it through B's member area has no membership at A, so A's own surfaces refuse them
and B's surfaces filter the row out by `makerspace_id`. The charge exists and is
undiscoverable.
"""

from django.db.models import Q

from apps.payments.models import Payment


def member_payment_queryset(user, makerspace_id):
    """Payments this member may act on from `makerspace_id`'s member area.

    Two arms:

    - Anything charged BY this makerspace -- unchanged, and still the whole story for every
      surface that predates collaborative events.
    - An event-registration charge raised by a DIFFERENT host, but only where the member's
      own registration records this makerspace as its provenance.

    The second arm is deliberately narrow. It keys on `registered_via_makerspace`, so it can
    only ever surface a charge the member incurred *through this space*; it never widens to
    "every payment this user has anywhere", which would flatten their unrelated makerspaces'
    charges into this one's member area.

    Note what is NOT gated here: the host's `events` module. Hiding a receipt or blocking a
    pending checkout because a module was switched off would make money disappear from the
    person who owes or paid it, and the separability contract keeps historical payment
    subjects usable even for a tombstoned app. Archival of the host is not filtered either,
    for the same reason -- the debt outlives the surface.
    """
    from apps.events.models import EventRegistration

    via_registration_ids = EventRegistration.objects.filter(
        member=user, registered_via_makerspace_id=makerspace_id,
    ).values_list("pk", flat=True)

    return Payment.objects.filter(
        Q(makerspace_id=makerspace_id)
        | Q(
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            subject_id__in=via_registration_ids,
        ),
        member=user,
    )
