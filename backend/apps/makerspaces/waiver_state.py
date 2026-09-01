"""Shared current and historical membership-waiver evidence predicates."""

from django.db.models import Q

from apps.makerspaces.models import MakerspaceWaiver


def _complete_self_acceptance(membership):
    return all(
        value is not None
        for value in (
            membership.accepted_waiver_id,
            membership.waiver_version_accepted,
            membership.waiver_accepted_at,
        )
    )


def _complete_witnessed_acceptance(membership):
    return all(
        value is not None
        for value in (
            membership.witnessed_waiver_id,
            membership.witnessed_waiver_version,
            membership.witnessed_at,
        )
    ) and (
        membership.witnessed_by_id is not None
        or membership.witnessed_actor_snapshot is not None
    )


def acceptance_on_file(membership):
    """Return whether either complete self or witnessed evidence tuple exists."""
    return _complete_self_acceptance(membership) or _complete_witnessed_acceptance(
        membership
    )


def acceptance_on_file_q(prefix=""):
    """SQL equivalent of ``acceptance_on_file`` for membership querysets."""
    field = lambda name: f"{prefix}{name}"
    self_acceptance = Q(
        **{
            f"{field('accepted_waiver_id')}__isnull": False,
            f"{field('waiver_version_accepted')}__isnull": False,
            f"{field('waiver_accepted_at')}__isnull": False,
        }
    )
    witnessed = Q(
        **{
            f"{field('witnessed_waiver_id')}__isnull": False,
            f"{field('witnessed_waiver_version')}__isnull": False,
            f"{field('witnessed_at')}__isnull": False,
        }
    ) & (
        Q(**{f"{field('witnessed_by_id')}__isnull": False})
        | Q(**{f"{field('witnessed_actor_snapshot')}__isnull": False})
    )
    return self_acceptance | witnessed


def active_waiver_for(makerspace_id):
    """Return the makerspace's current active waiver, or ``None``."""
    return (
        MakerspaceWaiver.objects.filter(makerspace_id=makerspace_id, is_active=True)
        .only("id", "version")
        .first()
    )


def current_acceptance(membership, *, active_waiver):
    """Return whether either complete tuple accepts the current active waiver.

    ``active_waiver`` is a REQUIRED keyword rather than something this function
    resolves for itself. An earlier version memoised it on the membership instance,
    which made a superseded waiver keep reading as current for the lifetime of that
    instance -- and every caller here iterates rows, so resolving it internally would
    otherwise be an N+1 per listing. Callers resolve it once with ``active_waiver_for``;
    most of them already hold it for their own null check.
    """
    waiver = active_waiver
    if waiver is None:
        return False
    self_current = _complete_self_acceptance(membership) and (
        membership.accepted_waiver_id == waiver.id
        and membership.waiver_version_accepted == waiver.version
    )
    witnessed_current = _complete_witnessed_acceptance(membership) and (
        membership.witnessed_waiver_id == waiver.id
        and membership.witnessed_waiver_version == waiver.version
    )
    return self_current or witnessed_current
