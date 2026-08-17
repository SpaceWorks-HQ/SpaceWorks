from django.core.exceptions import FieldDoesNotExist

from apps.makerspaces.models import Makerspace
from apps.tenant_migration.protocol_errors import TenantStateAdapterError

IMPORTING = "importing"
ACTIVE = "active"
ABORTED = "aborted"


def transition_target(makerspace_id, expected, new):
    """Database-enforced lifecycle transition against the separately owned field."""
    field_name = _state_field_name()
    return Makerspace.objects.filter(
        pk=makerspace_id,
        **{field_name: expected},
    ).update(**{field_name: new})


def target_has_state(makerspace_id, expected):
    field_name = _state_field_name()
    return Makerspace.objects.filter(
        pk=makerspace_id,
        **{field_name: expected},
    ).exists()


def _state_field_name():
    """Return the lifecycle field this adapter is deliberately coupled to."""
    try:
        Makerspace._meta.get_field("lifecycle_state")
    except FieldDoesNotExist as exc:
        raise TenantStateAdapterError(
            "Makerspace has no lifecycle_state field."
        ) from exc
    return "lifecycle_state"
