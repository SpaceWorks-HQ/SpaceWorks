"""Compatibility predicates for machine consumable pools."""

from django.db.models import Q

__all__ = ("pool_serves_machine", "pools_for_machine_q")


def pool_serves_machine(pool, machine) -> bool:
    """Return whether the pool belongs to the machine's tenant and scope."""
    return pool.makerspace_id == machine.makerspace_id and (
        pool.machine_id == machine.pk
        or (
            pool.machine_id is None
            and pool.machine_type_id == machine.machine_type_id
        )
        or (pool.machine_id is None and pool.machine_type_id is None)
    )


def pools_for_machine_q(machine) -> Q:
    """Return the queryset form of :func:`pool_serves_machine`."""
    return Q(makerspace_id=machine.makerspace_id) & (
        Q(machine_id=machine.pk)
        | Q(machine__isnull=True, machine_type_id=machine.machine_type_id)
        | Q(machine__isnull=True, machine_type__isnull=True)
    )
