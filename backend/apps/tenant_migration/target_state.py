from apps.makerspaces.models import Makerspace
from apps.tenant_migration.protocol_errors import TenantStateAdapterError

IMPORTING = "importing"
ACTIVE = "active"
ABORTED = "aborted"
REQUIRED_STATES = {IMPORTING, ACTIVE, ABORTED}


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
    """Discover the future lifecycle field by its closed state vocabulary."""
    for field in Makerspace._meta.concrete_fields:
        values = {value for value, _label in getattr(field, "choices", ())}
        if REQUIRED_STATES.issubset(values):
            return field.name
    raise TenantStateAdapterError(
        "Makerspace has no IMPORTING/ACTIVE/ABORTED lifecycle field yet."
    )
