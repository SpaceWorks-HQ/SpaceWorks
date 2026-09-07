"""Scheduled report delivery: API scoping, the beat-less run, skips and fail-safety."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.evidence.storage import StorageUnavailable
from apps.integrations.models_destinations import NotificationDestination
from apps.makerspaces.models import MakerspaceMembership
from apps.operations import report_schedule_services as services
from apps.operations.models import ReportDelivery, ReportSchedule
from apps.operations.report_schedule_services import run_report_schedules
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    stored, deleted = {}, []
    monkeypatch.setattr(services, "store_report_object", lambda key, payload, fmt: stored.__setitem__(key, payload))
    monkeypatch.setattr(services, "signed_download_url", lambda key: f"https://bucket.test/{key}?sig=1")
    monkeypatch.setattr(services, "delete_report_object", deleted.append)
    return {"stored": stored, "deleted": deleted}


def _schedule(space, creator, **overrides):
    values = {
        "makerspace": space, "report_key": "most-lent", "format": "csv", "cadence": "daily",
        "next_run_at": timezone.now() - timedelta(minutes=1), "created_by": creator,
        "recipient_emails": ["ops@example.test"],
    }
    values.update(overrides)
    return ReportSchedule.objects.create(**values)


def _url(space):
    return f"/api/v1/admin/makerspaces/{space.id}/report-schedules"


def test_staff_api_creates_lists_updates_and_deletes_a_schedule(fake_storage):
    space = make_space("sched-api")
    manager = make_member("sched-api-manager", space)
    destination = NotificationDestination.objects.create(
        makerspace=space, channel="telegram", label="Ops room", telegram_chat_id="-100",
    )
    client = authenticated_client(manager)

    created = client.post(_url(space), {
        "report_key": "most-lent", "format": "xlsx", "cadence": "weekly",
        "filters": {"window_days": 7}, "destination": destination.id,
        "recipient_emails": ["a@example.test"],
    }, format="json")
    assert created.status_code == 201, created.data
    assert created.data["filters"] == {"window_days": 7}
    assert created.data["created_by"] == manager.id
    schedule_id = created.data["id"]
    assert AuditLog.objects.filter(action="report_schedule.created", meta__schedule_id=schedule_id).exists()

    listed = client.get(_url(space))
    assert [row["id"] for row in listed.data["results"]] == [schedule_id]

    patched = client.patch(f"/api/v1/admin/report-schedules/{schedule_id}", {
        "filters": {"start": "2026-02-01", "end": "2026-01-01"},
    }, format="json")
    assert patched.status_code == 400
    patched = client.patch(f"/api/v1/admin/report-schedules/{schedule_id}", {"cadence": "monthly"}, format="json")
    assert patched.status_code == 200 and patched.data["cadence"] == "monthly"

    deleted = client.delete(f"/api/v1/admin/report-schedules/{schedule_id}")
    assert deleted.status_code == 204
    assert not ReportSchedule.objects.filter(pk=schedule_id).exists()


def test_schedule_needs_a_recipient_and_a_destination_from_the_same_makerspace():
    space = make_space("sched-validate")
    other = make_space("sched-validate-other")
    manager = make_member("sched-validate-manager", space)
    foreign = NotificationDestination.objects.create(
        makerspace=other, channel="slack", label="Theirs", webhook_url="x",
    )
    client = authenticated_client(manager)

    no_recipients = client.post(_url(space), {"report_key": "most-lent"}, format="json")
    foreign_room = client.post(_url(space), {"report_key": "most-lent", "destination": foreign.id}, format="json")
    not_exportable = client.post(_url(space), {"report_key": "summary", "recipient_emails": ["a@b.test"]}, format="json")

    assert no_recipients.status_code == 400 and "recipient_emails" in no_recipients.data
    assert foreign_room.status_code == 400 and "destination" in foreign_room.data
    assert not_exportable.status_code == 400 and "report_key" in not_exportable.data


def test_other_makerspace_manager_and_module_off_are_refused():
    space = make_space("sched-scope")
    stranger_space = make_space("sched-scope-other")
    manager = make_member("sched-scope-manager", space)
    stranger = make_member("sched-scope-stranger", stranger_space)
    schedule = _schedule(space, manager)

    stranger_client = authenticated_client(stranger)
    assert stranger_client.get(_url(space)).status_code == 404
    assert stranger_client.patch(
        f"/api/v1/admin/report-schedules/{schedule.id}", {"cadence": "weekly"}, format="json"
    ).status_code == 404
    assert stranger_client.post(f"/api/v1/admin/report-schedules/{schedule.id}/run-now").status_code == 404

    disable_module(space, "reports")
    own_client = authenticated_client(manager)
    assert own_client.get(_url(space)).status_code == 400
    assert own_client.post(f"/api/v1/admin/report-schedules/{schedule.id}/run-now").status_code == 400


def test_due_schedule_delivers_once_with_a_signed_link_and_advances(fake_storage):
    space = make_space("sched-run")
    manager = make_member("sched-run-manager", space)
    make_product(space, name="Sched Scope")
    schedule = _schedule(space, manager, filters={"window_days": 7})
    now = timezone.now()

    counts = run_report_schedules(now=now)
    again = run_report_schedules(now=now)

    assert counts == {"delivered": 1, "failed": 0, "skipped": 0}
    assert again == {"delivered": 0, "failed": 0, "skipped": 0}
    schedule.refresh_from_db()
    assert schedule.last_run_at == now
    assert schedule.next_run_at > now
    delivery = ReportDelivery.objects.get(schedule=schedule)
    assert delivery.status == "sent" and delivery.error == ""
    assert delivery.object_key.startswith(f"reports/{space.id}/most-lent/")
    assert delivery.expires_at > now
    payload = fake_storage["stored"][delivery.object_key].decode()
    assert payload.splitlines()[0].startswith(f"# generated_at={now.isoformat()} generated_by=schedule:{schedule.id} ")
    assert "product_name,times_lent,total_quantity_lent" in payload
    assert AuditLog.objects.filter(
        action="report_schedule.delivered", meta__schedule_id=schedule.id, meta__delivery_id=delivery.id,
    ).exists()


def test_archived_reports_disabled_and_creator_without_action_do_not_run():
    archived_space = make_space("sched-archived")
    archived_manager = make_member("sched-archived-manager", archived_space)
    _schedule(archived_space, archived_manager)
    archived_space.archived_at = timezone.now()
    archived_space.save(update_fields=["archived_at"])

    disabled_space = make_space("sched-disabled")
    disabled_manager = make_member("sched-disabled-manager", disabled_space)
    _schedule(disabled_space, disabled_manager)
    disable_module(disabled_space, "reports")

    lost_space = make_space("sched-lost")
    lost_manager = make_member("sched-lost-manager", lost_space)
    lost = _schedule(lost_space, lost_manager)
    MakerspaceMembership.objects.filter(user=lost_manager).delete()

    counts = run_report_schedules()

    assert counts == {"delivered": 0, "failed": 0, "skipped": 1}
    assert not ReportDelivery.objects.exists()
    lost.refresh_from_db()
    assert lost.next_run_at > timezone.now()
    assert AuditLog.objects.filter(action="report_schedule.skipped", meta__schedule_id=lost.id).exists()


def test_storage_or_provider_failure_records_failed_and_never_raises(monkeypatch, fake_storage):
    space = make_space("sched-fail")
    manager = make_member("sched-fail-manager", space)
    room = NotificationDestination.objects.create(
        makerspace=space, channel="telegram", label="Room", telegram_chat_id="-1",
    )
    space.set_telegram_bot_token("123:abc")
    space.save(update_fields=["telegram_bot_token"])
    storage_broken = _schedule(space, manager)
    room_broken = _schedule(space, manager, destination=room, recipient_emails=[])

    def failing_store(key, payload, fmt):
        if key.startswith(f"reports/{space.id}/") and storage_broken.deliveries.count() == 0 and not room_broken.deliveries.exists():
            raise StorageUnavailable()

    monkeypatch.setattr(services, "store_report_object", failing_store)
    import apps.integrations.telegram as telegram

    monkeypatch.setattr(telegram, "send_message", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    counts = run_report_schedules()

    assert counts["failed"] == 2 and counts["delivered"] == 0
    first = ReportDelivery.objects.get(schedule=storage_broken)
    assert first.status == "failed" and first.error == "build:StorageUnavailable" and first.object_key == ""
    second = ReportDelivery.objects.get(schedule=room_broken)
    assert second.status == "failed" and second.error.startswith("telegram:notification_delivery_failed")
    assert AuditLog.objects.filter(action="report_schedule.failed").count() == 2


def test_email_module_off_marks_the_email_leg_failed_and_run_now_returns_the_delivery():
    space = make_space("sched-email-off")
    manager = make_member("sched-email-off-manager", space)
    schedule = _schedule(space, manager, next_run_at=timezone.now() + timedelta(days=1))
    disable_module(space, "email")

    response = authenticated_client(manager).post(f"/api/v1/admin/report-schedules/{schedule.id}/run-now")

    assert response.status_code == 200, response.data
    assert response.data["status"] == "failed"
    assert response.data["error"] == "email:skipped"
    # The serializer presigns freshly (offline signature, no bucket round-trip) from the
    # stored key, so the URL names the private `reports/<makerspace_id>/` object.
    assert f"/reports/{space.id}/most-lent/" in response.data["download_url"]
    schedule.refresh_from_db()
    assert schedule.last_run_at is not None


def test_expired_delivery_objects_are_swept_on_the_next_run(fake_storage):
    space = make_space("sched-sweep")
    manager = make_member("sched-sweep-manager", space)
    schedule = _schedule(space, manager)
    stale = ReportDelivery.objects.create(
        schedule=schedule, object_key=f"reports/{space.id}/most-lent/old.csv", status="sent",
        expires_at=timezone.now() - timedelta(hours=1),
    )

    run_report_schedules()

    stale.refresh_from_db()
    assert stale.object_key == ""
    assert fake_storage["deleted"] == [f"reports/{space.id}/most-lent/old.csv"]
