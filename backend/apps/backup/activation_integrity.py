"""Shared inspection for Lane E activation completeness and equality."""

from dataclasses import dataclass

from django.db.models import Count

from apps.makerspaces.models import Makerspace

from .models import B1ActivationState


@dataclass(frozen=True)
class ActivationIntegrityIssue:
    kind: str
    makerspace_id: int
    flag_enabled: bool
    activation_state: str | None
    activation_count: int


def state_matches_flag(flag_enabled, state):
    return (
        flag_enabled and state == B1ActivationState.State.ON
    ) or (
        not flag_enabled
        and state in {
            B1ActivationState.State.OFF_PENDING,
            B1ActivationState.State.OFF_EFFECTIVE,
        }
    )


def inspect_activation_integrity():
    issues = []
    rows = tuple(
        Makerspace.objects.annotate(
            activation_count=Count("b1_activation_state")
        )
        .order_by("pk")
        .values("pk", "superadmin_access_enabled", "activation_count")
    )
    states = dict(
        B1ActivationState.objects.order_by("makerspace_id").values_list(
            "makerspace_id", "state"
        )
    )
    for row in rows:
        makerspace_id = row["pk"]
        flag_enabled = row["superadmin_access_enabled"]
        count = row["activation_count"]
        state = states.get(makerspace_id)
        if count != 1:
            issues.append(
                ActivationIntegrityIssue(
                    kind="activation_count",
                    makerspace_id=makerspace_id,
                    flag_enabled=flag_enabled,
                    activation_state=state,
                    activation_count=count,
                )
            )
            continue
        if not state_matches_flag(flag_enabled, state):
            issues.append(
                ActivationIntegrityIssue(
                    kind="flag_state_divergence",
                    makerspace_id=makerspace_id,
                    flag_enabled=flag_enabled,
                    activation_state=state,
                    activation_count=count,
                )
            )
    return tuple(issues)
