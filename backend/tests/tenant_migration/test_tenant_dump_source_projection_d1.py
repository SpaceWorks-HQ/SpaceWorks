from contextlib import ExitStack
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime

from apps.hardware_requests.models import HardwareRequest
from apps.machines.models import Machine, MachineOperator, MachineType
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.tenant_dump_source_projection import (
    TenantDumpProjectionError,
    project_makerspace_source,
    validate_machine_operator_closure,
)
from tests.encryption.conftest import enabled_encryption


pytestmark = pytest.mark.django_db


def _assignment_graph():
    space = Makerspace.objects.create(name="Lane D lab", slug="lane-d-lab")
    operator = get_user_model().objects.create_user(username="lane-d-operator")
    assigner = get_user_model().objects.create_user(username="lane-d-assigner")
    machine_type = MachineType.objects.create(
        makerspace=space,
        slug="lane-d-laser",
        name="Lane D laser",
    )
    machine = Machine.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name="Laser one",
        location="North bench",
    )
    assignment = MachineOperator.objects.create(
        machine=machine,
        user=operator,
        access_level=MachineOperator.AccessLevel.FULL,
        assigned_by=assigner,
    )
    return space, machine, assignment, operator, assigner


def test_machine_operator_travels_with_assignment_provenance():
    space, machine, assignment, operator, assigner = _assignment_graph()

    projection = project_makerspace_source(space.pk)

    rows = projection.rows["machines.MachineOperator"]
    assert len(rows) == 1
    assert rows[0]["machine_id"] == machine.pk
    assert rows[0]["user_id"] == operator.pk
    assert rows[0]["assigned_by_id"] == assigner.pk
    assert rows[0]["assigned_at"] == assignment.assigned_at
    manifest = projection.machine_operator_manifest[0]
    assert manifest["source_machine_operator_id"] == assignment.pk
    assert manifest["source_makerspace_id"] == space.pk
    assert manifest["source_machine_id"] == machine.pk
    assert manifest["source_user_id"] == operator.pk
    assert manifest["source_assigned_by_id"] == assigner.pk
    assert manifest["access_level"] == MachineOperator.AccessLevel.FULL
    assert parse_datetime(manifest["assigned_at"]) == assignment.assigned_at
    assert len(manifest["machine_fingerprint"]) == 64


@pytest.mark.parametrize("missing", ("machine", "user", "assigner"))
def test_machine_operator_closure_fails_when_a_referenced_row_is_absent(missing):
    space, _machine, _assignment, operator, assigner = _assignment_graph()
    projection = project_makerspace_source(space.pk)
    rows = dict(projection.rows)
    if missing == "machine":
        rows["machines.Machine"] = ()
    else:
        removed = operator.pk if missing == "user" else assigner.pk
        rows["accounts.User"] = tuple(
            row for row in rows["accounts.User"] if row["id"] != removed
        )

    with pytest.raises(TenantDumpProjectionError, match=f"{missing} absent"):
        validate_machine_operator_closure(rows, space.pk)


def test_source_projection_uses_lane_e_raw_guard_and_never_decrypts():
    with enabled_encryption():
        space, _machine, _assignment, operator, _assigner = _assignment_graph()
        HardwareRequest.objects.create(
            makerspace=space,
            requester=operator,
            requester_username=operator.username,
            requester_name="Encrypted requester",
            requester_contact_email="encrypted@example.test",
            requester_contact_phone="12345",
            requested_for="Lane D raw projection",
        )
        targets = (
            "apps.encryption.crypto.decrypt",
            "apps.encryption.crypto.decrypt_with_key_loader",
            "apps.encryption.services.get_dek",
            "apps.encryption.services.unwrap_dek",
            "apps.encryption.mappers.decrypt_with_key_loader",
            "apps.encryption.mappers.get_dek",
        )
        with ExitStack() as stack:
            spies = [
                stack.enter_context(mock.patch(target, side_effect=AssertionError(target)))
                for target in targets
            ]
            projection = project_makerspace_source(space.pk)

        assert all(spy.call_count == 0 for spy in spies)
        request_row = projection.rows["hardware_requests.HardwareRequest"][0]
        assert request_row["requester_name"].startswith("pii:gcm:v1:")
