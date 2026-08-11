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
      payment records this makerspace as its routing destination.

    The second arm is deliberately narrow. It keys on `Payment.via_makerspace`, so it can
    only ever surface a charge the member incurred *through this space*; it never widens to
    "every payment this user has anywhere", which would flatten their unrelated makerspaces'
    charges into this one's member area.

    Routing lives on the Payment row, so visibility does not depend on the events app at all
    and a module purge cannot sever it. Hiding a receipt or blocking a pending checkout
    because a module was switched off would make money disappear from the person who owes or
    paid it. Archival of the host is not filtered either, for the same reason -- the debt
    outlives the surface.
    """
    return Payment.objects.filter(
        Q(makerspace_id=makerspace_id)
        | Q(
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            via_makerspace_id=makerspace_id,
        ),
        member=user,
    )
