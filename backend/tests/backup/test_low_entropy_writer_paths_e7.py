import uuid

import pytest
from celery import shared_task
from django.core.management import BaseCommand, call_command
from django.db import connection

from apps.backup.models import B1ReservationEntry
from apps.operations.management.commands import run_scheduled_tasks
from apps.operations.models_scheduling import PeriodicTaskRun
from tests.backup.e7_reservation_test_helpers import (
    assert_database_rejects,
    digest,
    persist_active_reservation,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _reservation_fact(component_id):
    return {
        "version": "b1-broad-unique-fence-v1",
        "constraint_identity": digest("writer-path-rule"),
        "schema": "public",
        "table": "inventory_inventoryproduct",
        "columns": ["name"],
        "operations": ["insert", "update"],
        "component_ids": [str(component_id)],
        "definition_sha256": digest("writer-path-fence"),
    }


def _raw_delete(reservation_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM backup_b1reservationentry WHERE id = %s",
            [reservation_id],
        )


@shared_task(name="tests.backup.e7_delete_reservation_probe")
def _celery_delete_reservation(reservation_id):
    _raw_delete(reservation_id)


def _scheduled_delete_reservation():
    entry = B1ReservationEntry.objects.get(
        registry_identity=digest("writer-path-rule")
    )
    _raw_delete(entry.pk)


class _DeleteReservationCommand(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("reservation_id", type=int)

    def handle(self, *args, **options):
        _raw_delete(options["reservation_id"])


def _orm_delete(reservation_id):
    B1ReservationEntry.objects.filter(pk=reservation_id).delete()


def _celery_delete(reservation_id):
    _celery_delete_reservation.apply(args=(reservation_id,)).get(propagate=True)


def _management_delete(reservation_id):
    call_command(_DeleteReservationCommand(), str(reservation_id))


@pytest.mark.parametrize(
    "writer",
    (_orm_delete, _raw_delete, _celery_delete, _management_delete),
    ids=("orm", "raw-sql", "celery-worker", "management-command"),
)
def test_no_application_path_can_clear_an_active_reservation(writer):
    entry = persist_active_reservation(
        _reservation_fact(uuid.uuid4()), B1ReservationEntry.Kind.BROAD_FENCE
    )

    assert_database_rejects(lambda: writer(entry.pk))

    assert B1ReservationEntry.objects.filter(pk=entry.pk).exists()


def test_scheduled_cron_job_cannot_clear_an_active_reservation(monkeypatch):
    entry = persist_active_reservation(
        _reservation_fact(uuid.uuid4()), B1ReservationEntry.Kind.BROAD_FENCE
    )
    task_name = "e7-reservation-delete-probe"
    monkeypatch.setattr(
        run_scheduled_tasks,
        "SCHEDULED_TASKS",
        ((task_name, f"{__name__}._scheduled_delete_reservation", 1),),
    )
    monkeypatch.setattr(
        run_scheduled_tasks, "_import_task",
        lambda _path: _scheduled_delete_reservation,
    )

    call_command("run_scheduled_tasks", task=task_name)

    assert B1ReservationEntry.objects.filter(pk=entry.pk).exists()
    assert PeriodicTaskRun.objects.get(name=task_name).last_error
