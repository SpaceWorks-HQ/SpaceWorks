"""Lane E section 11 row 13: pre-cutover enforcement crash boundaries."""

import hashlib
import inspect
import json
import uuid

import pytest

from apps.backup import reservation_enforcement
from apps.backup.models import B1FenceContinuity, B1ReservationEntry
from tests.backup.e7_reservation_test_helpers import persist_restore_state


pytestmark = pytest.mark.django_db(transaction=True)


class SimulatedInstallCrash(RuntimeError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _fence(component_id):
    fact = {
        "version": "b1-broad-unique-fence-v1",
        "constraint_identity": "1" * 64,
        "schema": "public",
        "table": "inventory_inventoryproduct",
        "columns": ["name"],
        "operations": ["insert", "update"],
        "component_ids": [str(component_id)],
    }
    fact["definition_sha256"] = _digest(fact)
    return fact


@pytest.mark.parametrize(
    "boundary",
    ("before_reservation_row", "after_reservation_row", "after_continuity_row"),
)
def test_single_fence_install_rolls_back_at_each_internal_boundary(
    boundary, monkeypatch
):
    """The existing one-entry primitive must never leave half a fence behind."""

    component_id = uuid.uuid4()
    fact = _fence(component_id)
    operation_id, state_component_id = persist_restore_state(fact)
    assert state_component_id == component_id
    if boundary == "before_reservation_row":
        monkeypatch.setattr(
            reservation_enforcement,
            "_catalog_bound_payload",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                SimulatedInstallCrash(boundary)
            ),
        )
    elif boundary == "after_reservation_row":
        real_save = B1ReservationEntry.save

        def crash_after_reservation(row, *args, **kwargs):
            real_save(row, *args, **kwargs)
            raise SimulatedInstallCrash(boundary)

        monkeypatch.setattr(B1ReservationEntry, "save", crash_after_reservation)
    else:
        real_save = B1FenceContinuity.save

        def crash_after_continuity(row, *args, **kwargs):
            real_save(row, *args, **kwargs)
            raise SimulatedInstallCrash(boundary)

        monkeypatch.setattr(B1FenceContinuity, "save", crash_after_continuity)

    with pytest.raises(SimulatedInstallCrash, match=boundary):
        reservation_enforcement.install_reservation_entry(
            operation_id=operation_id,
            component_id=component_id,
            kind=B1ReservationEntry.Kind.BROAD_FENCE,
            fact=fact,
        )

    assert not B1ReservationEntry.objects.filter(operation_id=operation_id).exists()
    assert not B1FenceContinuity.objects.filter(operation_id=operation_id).exists()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC GAP: Lane E has no whole pre-cutover enforcement installer or "
        "resumable inter-entry crash boundary."
    ),
)
def test_whole_install_exposes_resumable_boundaries_before_stage_advance():
    """A future coordinator must expose the same crash-hook pattern as E5/E8."""

    installer = getattr(
        reservation_enforcement, "install_pre_cutover_enforcement", None
    )
    assert callable(installer)
    parameters = inspect.signature(installer).parameters
    assert {"operation_id", "manifest", "boundary_hook", "using"} <= set(parameters)
