"""Canonical policy for deciding whether a makerspace may serve traffic."""

from django.db.models import Q, QuerySet, Subquery

from apps.makerspaces.models import Makerspace


def is_servable(makerspace: Makerspace, *, allow_archived: bool = False) -> bool:
    """Return whether traffic may use it, optionally for archived recovery only."""
    from apps.backup.not_restored import is_not_restored

    return (
        makerspace.lifecycle_state == Makerspace.LifecycleState.ACTIVE
        and (allow_archived or makerspace.archived_at is None)
        and not is_not_restored(makerspace.pk)
    )


def servable_queryset(queryset: QuerySet | None = None, *, relation: str = ""):
    """Apply the canonical policy to a makerspace queryset or related queryset."""
    queryset = queryset if queryset is not None else Makerspace.objects.all()
    return queryset.filter(servable_q(relation))


def servable_q(relation: str = "") -> Q:
    """Return the canonical policy as a composable relation-aware query predicate."""
    from apps.backup.not_restored import active_makerspace_ids

    prefix = f"{relation}__" if relation else ""
    ordinary = Q(
        **{
            f"{prefix}archived_at__isnull": True,
            f"{prefix}lifecycle_state": Makerspace.LifecycleState.ACTIVE,
        }
    )
    return ordinary & ~Q(
        **{f"{prefix}pk__in": Subquery(active_makerspace_ids())}
    )


def unservable_makerspace_ids() -> set[int]:
    """Return IDs that every normal authorization scope must exclude."""
    from apps.backup.not_restored import active_component_states

    ordinary = archived_or_inactive_makerspace_ids()
    pending = set(
        active_component_states().values_list("makerspace_id_snapshot", flat=True)
    )
    return ordinary | pending


def archived_or_inactive_makerspace_ids() -> set[int]:
    """The archived/inactive half of the policy, without the not-restored half.

    A caller that must still let a pending (not-restored) tenant reach the
    not-restored write gate needs this rather than `unservable_makerspace_ids`,
    which unions both and would filter the tenant out before the gate ran.
    """
    return set(
        Makerspace.objects.exclude(
            archived_at__isnull=True,
            lifecycle_state=Makerspace.LifecycleState.ACTIVE,
        ).values_list("id", flat=True)
    )
