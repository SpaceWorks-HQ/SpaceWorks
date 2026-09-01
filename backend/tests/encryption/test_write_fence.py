import copy
import threading
import uuid
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, connection, models, transaction
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.encryption.models import PiiGlobalWriteFence, PiiMakerspaceWriteFence
from apps.encryption.registry import fields_for
from apps.encryption.write_fence import (
    PiiWriteFenced,
    assert_mapped_write_allowed,
    close_makerspace,
    fence_operation,
    reopen,
)
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.integrations.models import EmailLog
from apps.makerspaces.models import Makerspace
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceBucket


pytestmark = pytest.mark.django_db


def _rows():
    space = Makerspace.objects.create(name="Fence Space", slug=f"fence-{uuid.uuid4().hex[:12]}")
    user = get_user_model().objects.create_user(username=f"fence-{uuid.uuid4().hex[:10]}")
    now = timezone.now()
    event = Event.objects.create(
        makerspace=space, title="Fence event", starts_at=now, ends_at=now + timedelta(hours=2)
    )
    bookable = BookableSpace.objects.create(makerspace=space, name="Fence bench")
    machine_type = MachineType.objects.create(makerspace=space, slug=f"fence-{uuid.uuid4().hex[:8]}", name="Fence machine")
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Fence machine")
    service_bucket = ServiceBucket.objects.create(machine=machine, name="Fence service")
    return space, user, [
        HardwareRequest.objects.create(
            makerspace=space, requester=user, requester_username=user.username,
            requester_name="Fence requester", requester_contact_email="fence@example.test",
        ),
        EventRegistration.objects.create(event=event, name="Fence attendee", email="event@example.test", phone="1"),
        Booking.objects.create(
            space=bookable, name="Fence booker", email="booking@example.test", phone="1",
            starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1),
        ),
        MachineServiceRequest.objects.create(
            bucket=service_bucket, requester=user, title="Fence service",
            requester_name="Fence requester", contact_email="service@example.test", contact_phone="1",
        ),
        EmailLog.objects.create(
            makerspace=space, to_email="mail@example.test", subject="Fence", text_body="body"
        ),
    ]


def _clone(row):
    clone = copy.copy(row)
    for cache_name in ("_pii_plain_values", "_pii_raw_values", "_pii_original_plain_values"):
        clone.__dict__.pop(cache_name, None)
    clone.pk = None
    clone._state.adding = True
    clone._state.db = "default"
    for field in clone._meta.fields:
        if field.unique and not field.primary_key:
            if field.get_internal_type() == "UUIDField":
                setattr(clone, field.attname, uuid.uuid4())
    for field in fields_for(clone):
        value = clone.__dict__.get(field.field_name, "")
        if field.field_name == "email":
            value = f"fence-{uuid.uuid4().hex[:12]}@example.test"
        elif value:
            value = f"{value}-{uuid.uuid4().hex[:8]}"
        setattr(clone, field.field_name, value)
    if isinstance(clone, EventRegistration):
        clone.email_exact_hash = None
        clone.email_hash_generation = None
    return clone


def _raw_clone(row):
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {row._meta.db_table} SELECT * FROM {row._meta.db_table} WHERE id = %s",
            [row.pk],
        )


@pytest.mark.parametrize("enabled", [False, True])
def test_all_mapped_table_triggers_refuse_orm_raw_and_bulk_when_closed(enabled):
    from tests.encryption.conftest import enabled_encryption

    context = enabled_encryption() if enabled else nullcontext()
    with context:
        space, actor, rows = _rows()
        operation_id = close_makerspace(
            space.id, PiiMakerspaceWriteFence.OperationKind.DECRYPT_ROLLBACK, actor.id
        )
        for row in rows:
            with pytest.raises(PiiWriteFenced):
                _clone(row).save()
            with pytest.raises(DatabaseError), transaction.atomic():
                _raw_clone(row)
            with pytest.raises(DatabaseError), transaction.atomic():
                models.QuerySet(model=row.__class__).bulk_create([_clone(row)])

        reopen(operation_id, actor.id)
        for row in rows:
            _clone(row).save()
            mapped_field = fields_for(row)[0].field_name
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {row._meta.db_table} SET {mapped_field} = {mapped_field} WHERE id = %s",
                    [row.pk],
                )
            models.QuerySet(model=row.__class__).bulk_create([_clone(row)])


def test_fence_models_are_singleton_and_delete_guarded():
    space = Makerspace.objects.create(name="Fence Models", slug=f"fence-models-{uuid.uuid4().hex[:8]}")
    global_fence = PiiGlobalWriteFence.objects.get(pk=1)
    tenant_fence = PiiMakerspaceWriteFence.objects.get(makerspace=space)

    with transaction.atomic(), pytest.raises(Exception):
        PiiGlobalWriteFence.objects.create(pk=2)
    with pytest.raises(RuntimeError):
        global_fence.delete()
    with pytest.raises(RuntimeError):
        PiiGlobalWriteFence.objects.filter(pk=1).delete()
    with pytest.raises(RuntimeError):
        tenant_fence.delete()
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        tenant_fence.delete()
    assert not PiiMakerspaceWriteFence.objects.filter(pk=tenant_fence.pk).exists()


def test_matching_operation_guc_permits_only_its_closed_fence():
    space, actor, rows = _rows()
    operation_id = close_makerspace(
        space.id, PiiMakerspaceWriteFence.OperationKind.DECRYPT_ROLLBACK, actor.id
    )
    request = rows[0]
    request.requester_name = "blocked"
    with pytest.raises(PiiWriteFenced):
        request.save(update_fields=["requester_name"])
    with transaction.atomic(), fence_operation(operation_id):
        request.requester_name = "permitted"
        request.save(update_fields=["requester_name"])
    with transaction.atomic(), fence_operation(uuid.uuid4()):
        request.requester_name = "still blocked"
        with pytest.raises(PiiWriteFenced):
            request.save(update_fields=["requester_name"])


def test_provisioning_creates_and_purge_removes_the_tenant_fence(monkeypatch):
    from apps.makerspaces import lifecycle

    actor = get_user_model().objects.create_user(
        username=f"fence-purge-{uuid.uuid4().hex[:8]}", is_superuser=True
    )
    space = Makerspace.objects.create(name="Fence Purge", slug=f"fence-purge-{uuid.uuid4().hex[:8]}")
    assert PiiMakerspaceWriteFence.objects.filter(makerspace=space).exists()
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    space = lifecycle.archive(space, actor)
    lifecycle.purge(space, actor)
    assert not PiiMakerspaceWriteFence.objects.filter(makerspace_id=space.id).exists()


def test_close_and_open_commands_require_and_record_an_operation(capsys):
    actor = get_user_model().objects.create_user(
        username=f"fence-command-{uuid.uuid4().hex[:8]}", is_superuser=True
    )
    call_command(
        "close_pii_write_fence", "--global", "--operation-kind", "decrypt_rollback",
        "--actor-id", actor.id,
    )
    operation_id = capsys.readouterr().out.strip()
    assert PiiGlobalWriteFence.objects.get(pk=1).operation_id == uuid.UUID(operation_id)
    call_command("open_pii_write_fence", "--operation", operation_id, "--actor-id", actor.id)
    assert PiiGlobalWriteFence.objects.get(pk=1).state == PiiGlobalWriteFence.State.OPEN


def test_mapped_service_paths_fail_with_the_typed_503_exception(monkeypatch):
    from apps.bookings.services_bookings import create_booking
    from apps.events.services import register
    from apps.hardware_requests import request_workflow
    from apps.hardware_requests.exceptions import workflow_exception_handler
    from apps.integrations.dispatch import dispatch_email
    from apps.machines import service_workflow

    space, actor, rows = _rows()
    event = rows[1].event
    event.status = Event.Status.PUBLISHED
    event.save(update_fields=["status"])
    bookable = rows[2].space
    operation_id = close_makerspace(space.id, "decrypt_rollback", actor.id)
    with pytest.raises(PiiWriteFenced):
        register(event, name="Another", email="another@example.test", phone="1")
    with pytest.raises(PiiWriteFenced):
        create_booking(
            bookable, name="Another", email="another@example.test", phone="1",
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
        )
    with pytest.raises(PiiWriteFenced):
        request_workflow.submit_request(
            space,
            [],
            requester_principal=actor,
            contact_snapshot=request_workflow.RequesterSnapshot(
                username=actor.username,
                name=actor.display_name,
                email=actor.email,
                phone=actor.phone,
                contact_verified=True,
            ),
            audit_actor=actor,
        )
    with pytest.raises(PiiWriteFenced):
        service_workflow.submit(
            rows[3].bucket.machine, actor, requester_name="Another",
            contact_email="another@example.test", contact_phone="1", title="Fence",
        )
    with pytest.raises(PiiWriteFenced):
        service_workflow.accept(rows[3], actor)
    with pytest.raises(PiiWriteFenced):
        dispatch_email(
            makerspace=space, to_email="another@example.test", subject="Fence", text_body="body"
        )
    response = workflow_exception_handler(PiiWriteFenced(), {})
    assert response.status_code == 503
    assert response.data["code"] == "pii_write_fenced"
    reopen(operation_id, actor.id)


@pytest.mark.django_db(transaction=True)
def test_exclusive_close_waits_for_an_inflight_shared_writer():
    space = Makerspace.objects.create(name="Fence Locks", slug=f"fence-locks-{uuid.uuid4().hex[:8]}")
    actor = get_user_model().objects.create_user(username=f"fence-lock-{uuid.uuid4().hex[:8]}")
    PiiMakerspaceWriteFence.objects.get_or_create(makerspace=space)
    transaction.commit()
    started, finished = threading.Event(), threading.Event()

    def close():
        started.set()
        close_makerspace(space.id, "decrypt_rollback", actor.id)
        finished.set()

    with transaction.atomic():
        assert_mapped_write_allowed(space.id)
        thread = threading.Thread(target=close)
        thread.start()
        assert started.wait(1)
        assert not finished.wait(0.15)
    thread.join(timeout=2)
    assert finished.is_set()
    with transaction.atomic(), pytest.raises(PiiWriteFenced):
        assert_mapped_write_allowed(space.id)
