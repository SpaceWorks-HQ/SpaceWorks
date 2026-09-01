"""The one answer to "which registrations does this member hold in this space".

Shared by the profile counts, the profile's recent-attended list, member activity and the
check-in QR lookup, so those four cannot drift apart. It lives in the events app rather than
in `makerspaces` so it disappears with an events tombstone.

Three rules, each of which had a wrong alternative:

- **Provenance, not current collaboration.** An accepted collaboration authorizes discovery
  and creation; `registered_via_makerspace` records where the participation actually
  happened. Filtering on the live collaboration instead would let an administrator editing a
  collaborator list retroactively delete a member's history and silently break the QR of
  someone already holding a ticket.
- **But not past the host's own lifecycle.** Durable history survives a collaborator being
  removed; it must NOT survive the host being archived or withdrawing its events module,
  since the event itself is then not something the host exposes at all.
- **Never match on email.** `EventRegistration.member` is nullable, so an email-only public
  registration correctly never appears here. A shared household address is enough for an
  email match to attach one person's attendance to another person's published profile.
"""


def registrations_for_space(makerspace, user):
    """This member's registrations made via `makerspace`, while its host still exposes them."""
    from django.db.models import Q

    from apps.events.models import EventRegistration
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import module_enabled
    from apps.makerspaces.servability import servable_queryset

    registrations = servable_queryset(EventRegistration.objects.filter(
        # A NULL provenance falls back to the host, which is what every row meant before
        # provenance existed. This read fails OPEN to the previous behaviour on purpose: the
        # column is SET_NULL and can also be absent on a row written outside `register()`
        # (a superadmin in `/control/`, a data import), and a member's own history quietly
        # disappearing is a worse failure than showing a row whose routing is unknown. It
        # also means the backfill migration is a tidiness measure rather than load-bearing.
        Q(registered_via_makerspace=makerspace)
        | Q(registered_via_makerspace__isnull=True, event__makerspace=makerspace),
        member=user,
    ), relation="event__makerspace")
    # `module_enabled` needs the row, so the host set is resolved in Python. It is bounded by
    # the number of distinct hosts this member registered through -- one, for everybody who
    # never attended a joint event -- not by the number of registrations.
    host_ids = set(registrations.values_list("event__makerspace_id", flat=True))
    if not host_ids:
        return registrations.none()
    enabled = [
        host.pk
        for host in Makerspace.objects.filter(pk__in=host_ids)
        if module_enabled(host, "events")
    ]
    return registrations.filter(event__makerspace_id__in=enabled)
