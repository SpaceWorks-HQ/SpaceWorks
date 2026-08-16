"""Canonical policy for deciding whether a makerspace may serve traffic."""

from django.db.models import Q, QuerySet

from apps.makerspaces.models import Makerspace


def is_servable(makerspace: Makerspace, *, allow_archived: bool = False) -> bool:
    """Return whether traffic may use it, optionally for archived recovery only."""
    return (
        makerspace.lifecycle_state == Makerspace.LifecycleState.ACTIVE
        and (allow_archived or makerspace.archived_at is None)
    )


def servable_queryset(queryset: QuerySet | None = None, *, relation: str = ""):
    """Apply the canonical policy to a makerspace queryset or related queryset."""
    queryset = queryset if queryset is not None else Makerspace.objects.all()
    return queryset.filter(servable_q(relation))


def servable_q(relation: str = "") -> Q:
    """Return the canonical policy as a composable relation-aware query predicate."""
    prefix = f"{relation}__" if relation else ""
    return Q(
        **{
            f"{prefix}archived_at__isnull": True,
            f"{prefix}lifecycle_state": Makerspace.LifecycleState.ACTIVE,
        }
    )


def unservable_makerspace_ids() -> set[int]:
    """Return IDs that every normal authorization scope must exclude."""
    return set(
        Makerspace.objects.exclude(
            archived_at__isnull=True,
            lifecycle_state=Makerspace.LifecycleState.ACTIVE,
        ).values_list("id", flat=True)
    )
