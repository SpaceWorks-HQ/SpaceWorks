from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from apps.machines.intake import validate_intake, validate_intake_schema
from apps.machines.material_catalogue import catalogue, validate_selection
from apps.machines.models import MachineMaterial, MachineType
from apps.machines.printer_capabilities import PRINTER_CONFIG, validate_service_payload
from tests.return_helpers import make_space, make_member

pytestmark = pytest.mark.django_db

SCHEMA = {"version": 1, "fields": [
    {"key": "thickness", "label": "Thickness (mm)", "type": "number", "required": True, "min": 0.1, "max": 50},
    {"key": "quantity", "label": "Quantity", "type": "integer", "required": True, "min": 1},
]}


def world(slug):
    space = make_space(slug)
    space.enabled_features = sorted(set(space.enabled_features) | {"machines.material_catalogue", "machines.structured_intake"})
    space.save(update_fields=["enabled_features"])
    actor = make_member(slug+"-manager", space)
    printer = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    return space, actor, printer


def test_local_materials_do_not_edit_global_pack_or_other_space():
    space, _, printer = world("materials-local")
    other, _, _ = world("materials-other")
    old = dict(printer.capability_config)
    MachineMaterial.objects.create(makerspace=space, machine_type=printer, name="ASA", colours=["Orange"])
    validate_selection(space, printer, "ASA", "Orange")
    with pytest.raises(ValidationError):
        validate_selection(other, printer, "ASA", "Orange")
    printer.refresh_from_db()
    assert printer.capability_config == old
    assert "ASA" not in [row["name"] for row in catalogue(other, printer)]
    validate_service_payload(printer, {"requested_material": "ASA", "requested_color": "Orange", "quantity": 1}, makerspace=space)


@pytest.mark.parametrize("payload", [
    {"schema_version": 1, "values": {"thickness": 2}},
    {"schema_version": 2, "values": {"thickness": 2, "quantity": 1}},
    {"schema_version": 1, "values": {"thickness": 100, "quantity": 1}},
    {"schema_version": 1, "values": {"thickness": 2, "quantity": True}},
    {"schema_version": 1, "values": {"thickness": 2, "quantity": 1, "owner_id": 99}},
])
def test_structured_intake_rejects_missing_stale_out_of_range_and_unknown(payload):
    space, _, _ = world("intake-validation"+str(len(str(payload))))
    machine_type = SimpleNamespace(intake_schema=SCHEMA)
    with pytest.raises(ValidationError):
        validate_intake(space, machine_type, payload)


def test_intake_accepts_valid_shape_and_rejects_reference_schema():
    space, _, _ = world("intake-good")
    validate_intake_schema(SCHEMA)
    validate_intake(space, SimpleNamespace(intake_schema=SCHEMA),
                    {"schema_version": 1, "values": {"thickness": 2.5, "quantity": 1}})
    with pytest.raises(ValidationError):
        validate_intake_schema({"version": 1, "fields": [{"key": "user_id", "label": "User", "type": "integer"}]})
    with pytest.raises(ValidationError):
        validate_intake_schema({"version": 1, "fields": [{"key": "size", "label": "Size", "type": "number", "max": 10**500}]})


def test_material_write_foreign_type_refused_and_builtin_intake_protected():
    space, actor, printer = world("material-api")
    other = make_space("material-api-other")
    foreign = MachineType.objects.create(makerspace=other, slug="custom", name="Other custom")
    client = APIClient()
    client.force_authenticate(actor)
    url = reverse("machine-materials", kwargs={"makerspace_id": space.pk})
    assert client.post(url, {"machine_type": foreign.pk, "name": "Wood", "colours": ["Natural"]}, format="json").status_code == 400
    url = reverse("machine-type-intake", kwargs={"makerspace_id": space.pk, "type_id": printer.pk})
    assert client.put(url, {"intake_schema": SCHEMA}, format="json").status_code == 400


def test_public_intake_never_discloses_private_or_foreign_custom_type_schema():
    from apps.machines.models import Machine
    space, _, _ = world("intake-public")
    custom = MachineType.objects.create(makerspace=space, slug="laser", name="Laser", intake_schema=SCHEMA)
    url = reverse("public-machine-intake", kwargs={"makerspace_slug": space.slug, "type_id": custom.pk})
    client = APIClient()
    assert client.get(url).status_code == 404
    machine = Machine.objects.create(makerspace=space, machine_type=custom, name="Laser", is_public=True)
    response = client.get(url)
    assert response.status_code == 200 and response.data["intake_schema"] == SCHEMA
    other, _, _ = world("intake-public-other")
    assert client.get(reverse("public-machine-intake", kwargs={"makerspace_slug": other.slug, "type_id": custom.pk})).status_code == 404
    machine.is_public = False
    machine.save(update_fields=["is_public"])
    assert client.get(url).status_code == 404


def test_material_and_intake_inputs_reject_ignored_fields_and_scope_foreign_keys():
    space, actor, printer = world("material-strict")
    client = APIClient()
    client.force_authenticate(actor)
    payload = {"machine_type": printer.pk, "name": "ASA", "colours": ["Orange"]}
    url = reverse("machine-materials", kwargs={"makerspace_id": space.pk})
    assert client.post(url, {**payload, "makerspace": space.pk}, format="json").status_code == 400
    response = client.post(url, payload, format="json")
    assert response.status_code == 201
    custom = MachineType.objects.create(makerspace=space, slug="strict-laser", name="Laser")
    intake_url = reverse("machine-type-intake", kwargs={"makerspace_id": space.pk, "type_id": custom.pk})
    assert client.put(intake_url, {"intake_schema": SCHEMA, "ignored": True}, format="json").status_code == 400
    assert client.put(intake_url, {"intake_schema": SCHEMA}, format="json").status_code == 200
    custom.refresh_from_db()
    assert custom.intake_schema == SCHEMA
    from apps.audit.models import AuditLog
    assert AuditLog.objects.filter(makerspace=space, actor=actor, action="machine.material_created").exists()
    assert AuditLog.objects.filter(makerspace=space, actor=actor, action="machine.intake_updated").exists()


def test_custom_intake_is_validated_by_public_submission_workflow():
    from apps.machines.models import Machine, MachineServiceRequest
    space, actor, _ = world("intake-submit")
    custom = MachineType.objects.create(makerspace=space, slug="submit-laser", name="Laser", intake_schema=SCHEMA)
    machine = Machine.objects.create(makerspace=space, machine_type=custom, name="Laser", is_public=True)
    from tests.member_submission import active_member_client
    actor, client = active_member_client(space, "intake-submit-requester")
    url = reverse("public-machine-service-request-submit", kwargs={"makerspace_slug": space.slug})
    data = {"machine_id": machine.pk, "title": "Cut plywood", "capability_payload": {
        "schema_version": 1, "values": {"thickness": 2.5, "quantity": 1},
    }}
    assert client.post(url, {**data, "capability_payload": {"schema_version": 1, "values": {}}}, format="json").status_code == 400
    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
    response = client.post(url, data, format="json")
    assert response.status_code == 201
    saved = MachineServiceRequest.objects.get(makerspace=space)
    assert saved.capability_payload == data["capability_payload"] and saved.requester_id == actor.pk
