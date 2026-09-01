"""Persistent fail-closed lookup for Lane E opaque tenant components."""


class TenantNotRestored(RuntimeError):
    """The selected tenant exists in an opaque component, not the readable main."""


def active_component_states():
    from apps.backup.models import B1RestoreComponentState

    return B1RestoreComponentState.objects.exclude(
        state=B1RestoreComponentState.State.RESTORED
    )


def active_makerspace_ids():
    return active_component_states().values("makerspace_id_snapshot")


def is_not_restored(makerspace_id):
    if makerspace_id is None:
        return False
    return active_component_states().filter(
        makerspace_id_snapshot=int(makerspace_id)
    ).exists()


def assert_restored(makerspace_id):
    if is_not_restored(makerspace_id):
        raise TenantNotRestored(
            "This makerspace is present in an opaque archive component and is not restored."
        )


def assert_deployment_fully_restored():
    if active_component_states().exists():
        raise TenantNotRestored(
            "A deployment archive cannot treat opaque, not-restored tenants as absent."
        )
