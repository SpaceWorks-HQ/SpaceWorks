import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.machines.models import MachineConsumablePool, MachineType
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.makerspaces.models import MakerspaceMembership
from tests.machines.test_machine_scope_authorization import _manager
from tests.machines.test_machine_scope_surfaces import client_for, lab
from tests.return_helpers import make_member


pytestmark = pytest.mark.django_db


def _pool(space, material, **scope):
    return MachineConsumablePool.objects.create(
        makerspace=space,
        material=material,
        initial_grams="100",
        remaining_grams="100",
        **scope,
    )


def _pool_url(space):
    return reverse("admin-machine-service-printer-pools", args=[space.pk])


def _printer_type():
    printer_type, _ = MachineType.objects.get_or_create(
        makerspace=None,
        slug="3d_printer",
        defaults={
            "name": "3D Printer",
            "is_builtin": True,
            "capability_config": PRINTER_CONFIG,
        },
    )
    return printer_type


def test_pool_list_honours_type_and_individual_machine_role_scope(lab):
    type_a_pool = _pool(
        lab["space"], "Type A stock", machine_type=lab["printer_type"]
    )
    type_b_pool = _pool(
        lab["space"], "Type B stock", machine_type=lab["laser_type"]
    )
    shared_pool = _pool(lab["space"], "Shared stock")

    type_scoped = client_for(lab["printer_mgr"]).get(_pool_url(lab["space"]))
    machine_manager = _manager(
        lab["space"], "single-printer-manager", machine=lab["printer"]
    )
    machine_scoped = client_for(machine_manager).get(_pool_url(lab["space"]))

    assert type_scoped.status_code == 200
    type_scoped_ids = {row["id"] for row in type_scoped.data}
    assert {type_a_pool.pk, shared_pool.pk} <= type_scoped_ids
    assert type_b_pool.pk not in type_scoped_ids
    assert type_a_pool.pk in {row["id"] for row in machine_scoped.data}


def test_pool_create_refuses_a_machine_type_outside_the_actors_scope(lab):
    response = client_for(lab["printer_mgr"]).post(
        _pool_url(lab["space"]),
        {
            "machine_type_id": lab["laser_type"].pk,
            "material": "Unauthorized stock",
            "quantity": "100",
        },
        format="json",
    )

    assert response.status_code == 404
    assert not MachineConsumablePool.objects.filter(
        makerspace=lab["space"], material="Unauthorized stock"
    ).exists()


def test_pool_create_rejects_both_machine_and_machine_type_scope(lab):
    response = client_for(lab["printer_mgr"]).post(
        _pool_url(lab["space"]),
        {
            "machine_id": lab["printer"].pk,
            "machine_type_id": lab["printer_type"].pk,
            "material": "Ambiguous stock",
            "quantity": "100",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "machine_type_id" in response.data


def test_printer_type_pool_create_rejects_a_non_gram_unit(lab):
    manager = make_member(
        "printer-unit-space-manager",
        lab["space"],
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    )

    response = client_for(manager).post(
        _pool_url(lab["space"]),
        {
            "machine_type_id": _printer_type().pk,
            "material": "Liquid printer stock",
            "unit": "milliliters",
            "quantity": "100",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "unit" in response.data


def test_visibility_patch_updates_the_pool_and_records_an_audit_event(lab):
    pool = _pool(
        lab["space"], "Visible type stock", machine_type=lab["printer_type"]
    )

    response = client_for(lab["printer_mgr"]).patch(
        reverse("admin-machine-service-printer-pool-detail", args=[pool.pk]),
        {"is_public": False},
        format="json",
    )

    assert response.status_code == 200
    pool.refresh_from_db()
    event = AuditLog.objects.get(
        action="machine_consumable_pool.visibility_changed",
        target_id=str(pool.pk),
    )
    assert response.data["is_public"] is False
    assert pool.is_public is False
    assert event.actor_id == lab["printer_mgr"].pk
    assert event.makerspace_id == lab["space"].pk
    assert event.meta == {"pool_id": pool.pk, "from": True, "to": False}
