from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts.models import User
from apps.makerspaces import archive_requests
from apps.makerspaces.models import Makerspace, MakerspaceArchiveRequest, MakerspaceMembership

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_manager(makerspace, username):
    actor = User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
    )
    MakerspaceMembership.objects.create(makerspace=makerspace, user=actor)
    return actor


def test_database_rejects_two_pending_requests_for_one_space():
    makerspace = make_space("archive-unique")
    first = MakerspaceArchiveRequest.objects.create(makerspace=makerspace, reason="First")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MakerspaceArchiveRequest.objects.create(makerspace=makerspace, reason="Second")

    first.status = MakerspaceArchiveRequest.Status.WITHDRAWN
    first.resolved_at = timezone.now()
    first.save(update_fields=["status", "resolved_at"])
    assert MakerspaceArchiveRequest.objects.create(makerspace=makerspace, reason="Second").pk


def test_pending_unique_integrity_error_is_returned_as_a_typed_conflict(monkeypatch):
    makerspace = make_space("archive-integrity-translation")
    actor = make_manager(makerspace, "archive-integrity-manager")
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)

    def conflict(**_kwargs):
        raise IntegrityError(
            'duplicate key violates unique constraint '
            f'"{archive_requests.PENDING_CONSTRAINT}"'
        )

    monkeypatch.setattr(MakerspaceArchiveRequest.objects, "create", conflict)
    with pytest.raises(archive_requests.PendingArchiveRequestExists) as caught:
        archive_requests.create(makerspace, actor, "Close it")

    assert caught.value.detail["code"] == "pending_archive_request_exists"


@pytest.mark.django_db(transaction=True)
def test_concurrent_service_creates_have_one_typed_winner(monkeypatch):
    makerspace = make_space("archive-concurrent")
    actors = (
        make_manager(makerspace, "archive-concurrent-manager-1"),
        make_manager(makerspace, "archive-concurrent-manager-2"),
    )
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    gate = Barrier(2)

    def create_one(index):
        close_old_connections()
        try:
            gate.wait(timeout=5)
            try:
                archive_requests.create(
                    Makerspace.objects.get(pk=makerspace.pk),
                    User.objects.get(pk=actors[index].pk),
                    f"Reason {index}",
                )
                return "created"
            except APIException as exc:
                return str(exc.detail["code"])
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(create_one, range(2)))

    assert outcomes == ["created", "pending_archive_request_exists"]
    assert MakerspaceArchiveRequest.objects.filter(makerspace=makerspace).count() == 1
