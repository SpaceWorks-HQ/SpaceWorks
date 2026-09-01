"""Public printer surfaces use the global built-in type, not a tenant slug match."""

from decimal import Decimal
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient

from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    MachineUsageEntry,
    ServiceQueue,
)
from apps.machines.public_printer_service import public_queues, public_status
from apps.machines.public_printer_stats import build_public_printer_stats
from apps.machines.service_reports import build_printer_service_report
from tests.return_helpers import authenticated_client, make_member, make_space, make_user


pytestmark = pytest.mark.django_db


@pytest.fixture
def printer_type_collision():
    space = make_space("printer-global-identity")
    space.public_stats_enabled = True
    space.save(update_fields=["public_stats_enabled"])
    requester = make_user("printer-global-identity-requester")
    global_type = MachineType.objects.get(
        makerspace__isnull=True,
        slug="3d_printer",
    )
    local_type = MachineType.objects.create(
        makerspace=space,
        slug="3d_printer",
        name="Tenant collision type",
    )
    global_machine = Machine.objects.create(
        makerspace=space,
        machine_type=global_type,
        name="Built-in printer",
        type_payload={"model": "Global Model"},
    )
    local_machine = Machine.objects.create(
        makerspace=space,
        machine_type=local_type,
        name="Tenant collision machine",
    )
    global_queue = ServiceQueue.objects.create(
        makerspace=space,
        machine_type=global_type,
        name="Built-in printer queue",
    )
    local_queue = ServiceQueue.objects.create(
        makerspace=space,
        machine_type=local_type,
        name="Tenant collision queue",
    )

    def request(queue, machine, title, status, *, minutes=0, grams="0"):
        return MachineServiceRequest.objects.create(
            makerspace=space,
            queue=queue,
            requester=requester,
            requester_name=requester.username,
            assigned_machine=machine,
            title=title,
            status=status,
            actual_minutes=minutes,
            actual_consumed_grams=Decimal(grams),
            completed_at=(
                timezone.now()
                if status == MachineServiceRequest.Status.COMPLETED
                else None
            ),
            run_machine_model=(machine.type_payload or {}).get("model", ""),
        )

    global_pending = request(
        global_queue,
        global_machine,
        "Built-in pending job",
        MachineServiceRequest.Status.PENDING,
    )
    local_pending = request(
        local_queue,
        local_machine,
        "Tenant collision pending job",
        MachineServiceRequest.Status.PENDING,
    )
    request(
        global_queue,
        global_machine,
        "Built-in completed job",
        MachineServiceRequest.Status.COMPLETED,
        minutes=60,
        grams="10",
    )
    request(
        local_queue,
        local_machine,
        "Tenant collision completed job",
        MachineServiceRequest.Status.COMPLETED,
        minutes=120,
        grams="50",
    )
    MachineUsageEntry.objects.create(
        machine=global_machine,
        source=MachineUsageEntry.Source.TYPED_MANUAL,
        hours=Decimal("1.50"),
        consumed_grams=Decimal("5"),
    )
    MachineUsageEntry.objects.create(
        machine=local_machine,
        source=MachineUsageEntry.Source.TYPED_MANUAL,
        hours=Decimal("3.00"),
        consumed_grams=Decimal("20"),
    )
    return {
        "space": space,
        "global_queue": global_queue,
        "local_queue": local_queue,
        "global_pending": global_pending,
        "local_pending": local_pending,
        "global_machine": global_machine,
        "local_machine": local_machine,
    }


def test_public_printer_queues_only_list_the_global_builtin_type(printer_type_collision):
    rows = APIClient().get(
        reverse(
            "public-printer-service-queues",
            args=[printer_type_collision["space"].slug],
        )
    )

    assert rows.status_code == 200
    assert [row["id"] for row in rows.data] == [
        printer_type_collision["global_queue"].pk
    ]


def test_public_printer_status_rejects_the_tenant_slug_collision(printer_type_collision):
    local_response = APIClient().get(
        reverse(
            "public-printer-service-status",
            args=[printer_type_collision["local_pending"].public_token],
        )
    )
    global_response = APIClient().get(
        reverse(
            "public-printer-service-status",
            args=[printer_type_collision["global_pending"].public_token],
        )
    )

    assert local_response.status_code == 404
    assert global_response.status_code == 200
    assert global_response.data["title"] == "Built-in pending job"


def test_public_printer_stats_only_count_the_global_builtin_type(printer_type_collision):
    response = APIClient().get(
        reverse(
            "public-makerspace-stats",
            args=[printer_type_collision["space"].slug],
        )
    )

    assert response.status_code == 200
    printing = response.data["printing"]
    assert printing["hours_all_time"] == 2.5
    assert printing["grams_all_time"] == 15.0
    assert printing["jobs"]["status_counts"]["pending"] == 1
    assert printing["jobs"]["completed"] == 1
    assert [row["name"] for row in printing["per_printer"]] == ["Built-in printer"]


def test_printer_service_report_only_uses_the_global_builtin_type(printer_type_collision):
    manager = make_member(
        "printer-global-identity-manager",
        printer_type_collision["space"],
    )
    response = authenticated_client(manager).get(
        reverse(
            "admin-makerspace-machine-service-report",
            args=[printer_type_collision["space"].pk],
        ),
        {"machine_type": "3d_printer"},
    )

    assert response.status_code == 200
    assert set(response.data) == {"printer_metrics"}
    assert [row["machine_id"] for row in response.data["printer_metrics"]] == [
        printer_type_collision["global_machine"].pk
    ]
    assert response.data["printer_metrics"][0]["completed_hours"] == 1.0
    assert response.data["printer_metrics"][0]["manual_hours"] == 1.5


def test_missing_global_printer_type_returns_empty_public_surfaces():
    MachineType.objects.get(
        makerspace__isnull=True,
        slug="3d_printer",
    ).delete()
    space = make_space("missing-global-printer-type")

    assert list(public_queues(space)) == []
    with pytest.raises(NotFound):
        public_status(uuid.uuid4())

    stats = build_public_printer_stats(space)
    assert stats["per_printer"] == []
    assert stats["jobs"]["completed"] == 0
    assert build_printer_service_report(space.pk).records == []
