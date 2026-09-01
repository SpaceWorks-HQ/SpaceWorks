"""The serialized owner of the access-flag side of Lane E activation."""


from django.db import transaction
from django.dispatch import Signal

from apps.audit import services as audit

from .activation_integrity import state_matches_flag
from .custody import RECIPIENT_FLOOR, with_makerspace_custody_lock
from .models import B1ActivationState


access_switch_committed = Signal()


class ActivationStateInvariantError(RuntimeError):
    """The access flag and durable activation row cannot be changed safely."""


class ActivationRecipientFloorError(ActivationStateInvariantError):
    """Sovereign activation was requested without the admission recipient floor."""


def set_superadmin_access(custody, *, enabled, actor):
    """Write the flag, activation row and audit under an existing custody lock."""
    makerspace = custody.makerspace
    activation = _locked_activation(makerspace.pk)
    _assert_equal(makerspace.superadmin_access_enabled, activation.state)

    if not isinstance(enabled, bool):
        raise ActivationStateInvariantError(
            "The superadmin-access switch requires a boolean value."
        )
    if makerspace.superadmin_access_enabled == enabled:
        return activation

    before = activation.state
    if enabled:
        if before not in {
            B1ActivationState.State.OFF_PENDING,
            B1ActivationState.State.OFF_EFFECTIVE,
        }:
            raise ActivationStateInvariantError(
                f"Cannot re-enable superadmin access from activation state {before!r}."
            )
        activation.state = B1ActivationState.State.ON
        activation.effective_artifact_id = None
        activation.effective_at = None
    else:
        if before != B1ActivationState.State.ON:
            raise ActivationStateInvariantError(
                f"Cannot disable superadmin access from activation state {before!r}."
            )
        if custody.verified_recipient_count() < RECIPIENT_FLOOR:
            raise ActivationRecipientFloorError(
                "At least two verified archive recipients are required."
            )
        activation.state = B1ActivationState.State.OFF_PENDING

    makerspace.superadmin_access_enabled = enabled
    makerspace.save(update_fields=("superadmin_access_enabled", "updated_at"))
    activation.save(
        update_fields=(
            "state",
            "effective_artifact_id",
            "effective_at",
            "updated_at",
        )
    )
    audit.record(
        actor,
        "makerspace.superadmin_access_changed",
        makerspace=makerspace,
        target=makerspace,
        meta={
            "enabled": enabled,
            "activation_before": before,
            "activation_after": activation.state,
        },
    )
    # A bare functools.partial has no __qualname__, and Django's robust on_commit
    # handler formats its failure message with func.__qualname__ -- so a failing
    # receiver made the ERROR HANDLER raise, defeating robust=True entirely.
    transaction.on_commit(
        lambda makerspace_id=makerspace.pk, enabled=enabled: (
            access_switch_committed.send(
                sender=set_superadmin_access,
                makerspace_id=makerspace_id,
                enabled=enabled,
            )
        ),
        robust=True,
    )
    return activation


def repair_activation_state(makerspace_id, *, actor):
    """Conservatively restore the activation row to the live access flag."""
    with with_makerspace_custody_lock(makerspace_id) as custody:
        makerspace = custody.makerspace
        activation = (
            B1ActivationState.objects.select_for_update()
            .filter(makerspace_id=makerspace.pk)
            .first()
        )
        before = activation.state if activation is not None else None
        if activation is None:
            activation = B1ActivationState(makerspace=makerspace)

        if makerspace.superadmin_access_enabled:
            target = B1ActivationState.State.ON
        elif before in {
            B1ActivationState.State.OFF_PENDING,
            B1ActivationState.State.OFF_EFFECTIVE,
        }:
            return activation
        else:
            target = B1ActivationState.State.OFF_PENDING

        if before == target:
            return activation
        activation.state = target
        activation.effective_artifact_id = None
        activation.effective_at = None
        activation.save()
        audit.record(
            actor,
            "backup.activation_state_repaired",
            makerspace=makerspace,
            target=activation,
            meta={
                "flag_enabled": makerspace.superadmin_access_enabled,
                "activation_before": before,
                "activation_after": target,
            },
        )
        return activation


def _locked_activation(makerspace_id):
    try:
        return B1ActivationState.objects.select_for_update().get(
            makerspace_id=makerspace_id
        )
    except B1ActivationState.DoesNotExist as exc:
        raise ActivationStateInvariantError(
            "The makerspace has no Lane E activation row; run the repair command."
        ) from exc


def _assert_equal(flag_enabled, state):
    if not state_matches_flag(flag_enabled, state):
        raise ActivationStateInvariantError(
            f"The superadmin-access flag diverges from activation state {state!r}."
        )
