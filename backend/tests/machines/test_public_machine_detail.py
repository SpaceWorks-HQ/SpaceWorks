import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.machines.models import Machine, MachineServiceRequest, ServiceQueue
from apps.machines import services
from tests.maintenance.helpers import make_machine_setup
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def world(slug):
    space, actor, machine, _ = make_machine_setup(slug)
    space.enabled_features = sorted(set(space.enabled_features) | {"machines.public_detail"})
    space.save(update_fields=["enabled_features"])
    machine.is_public = True
    machine.location = "Secret shelf"
    machine.camera_feed_url = "https://username:password@example.com/private"
    machine.save()
    return space, actor, machine


def url(space, machine):
    return reverse("public-machine-detail", kwargs={"makerspace_slug": space.slug, "pk": machine.pk})


def test_allowlist_defaults_and_status_since_survives_non_status_update():
    space, actor, machine = world("public-detail")
    client = APIClient()
    response = client.get(url(space, machine))
    assert response.status_code == 200
    assert response.data["queue"] is None and response.data["training_required"] is None
    assert "location" not in response.data and "camera_feed_url" not in response.data
    assert "password" not in str(response.data)
    machine.refresh_from_db()
    old = machine.status_since
    Machine.objects.filter(pk=machine.pk).update(name="New name")
    machine.refresh_from_db()
    assert machine.status_since == old
    services.set_status(machine, actor, Machine.Status.OFFLINE)
    machine.refresh_from_db()
    assert machine.status_since >= old


def test_queue_is_aggregate_estimate_unknown_jobs_do_not_claim_zero():
    space, actor, machine = world("public-queue")
    machine.public_fields = ["queue_eta", "training"]
    machine.save(update_fields=["public_fields"])
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=machine.machine_type, name="Jobs")
    MachineServiceRequest.objects.create(makerspace=space, queue=queue, requester=actor,
                                         title="Private title", status="accepted", estimated_minutes=120)
    response = APIClient().get(url(space, machine))
    assert response.data["queue"] == {"length": 1, "eta_minutes": 120}
    assert "Private title" not in str(response.data)
    MachineServiceRequest.objects.create(makerspace=space, queue=queue, requester=actor,
                                         title="Unknown", status="accepted", estimated_minutes=0)
    assert APIClient().get(url(space, machine)).data["queue"]["eta_minutes"] is None


def test_module_off_400_and_private_foreign_machines_404():
    space, _, machine = world("detail-gates")
    other, _, foreign = world("detail-foreign")
    assert APIClient().get(url(space, foreign)).status_code == 404
    machine.is_public = False
    machine.save(update_fields=["is_public"])
    assert APIClient().get(url(space, machine)).status_code == 404
    disable_module(space, "machines")
    assert APIClient().get(url(space, machine)).status_code == 400


def test_global_admin_hiding_does_not_hide_the_public_catalogue():
    space, _, machine = world("detail-hidden-admin")
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    assert APIClient().get(url(space, machine)).status_code == 200


def test_disclosures_are_persisted_on_create_and_invalid_fields_are_refused():
    space, actor, machine = world("detail-create")
    client = APIClient()
    client.force_authenticate(actor)
    create_url = reverse("admin-machines", kwargs={"makerspace_id": space.pk})
    data = {"name": "Another laser", "machine_type": machine.machine_type_id,
            "type_payload": {}, "public_fields": ["training", "queue_eta"]}
    assert client.post(create_url, {**data, "public_fields": ["camera_feed_url"]}, format="json").status_code == 400
    response = client.post(create_url, data, format="json")
    assert response.status_code == 201 and response.data["public_fields"] == data["public_fields"]
    saved = Machine.objects.get(pk=response.data["id"])
    assert saved.public_fields == data["public_fields"]
