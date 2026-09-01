import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import archive_requests, lifecycle
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceArchiveRequest,
    MakerspaceMembership,
)

pytestmark = pytest.mark.django_db


def user(username, *, role=User.Role.REQUESTER, **overrides):
    values = {
        "email": f"{username}@example.test",
        "access_status": User.AccessStatus.ACTIVE,
    }
    values.update(overrides)
    return User.objects.create_user(username=username, role=role, **values)


def space(slug, **overrides):
    return Makerspace.objects.create(name=slug, slug=slug, **overrides)


def manager(makerspace, username="archive-manager"):
    actor = user(username, role=User.Role.SPACE_MANAGER, is_staff=True)
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def superadmin(username="archive-superadmin"):
    return user(
        username,
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def list_url(makerspace):
    return reverse(
        "admin-makerspace-archive-requests",
        kwargs={"makerspace_id": makerspace.pk},
    )


def withdraw_url(archive_request):
    return reverse(
        "admin-makerspace-archive-request-withdraw",
        kwargs={
            "makerspace_id": archive_request.makerspace_id,
            "pk": archive_request.pk,
        },
    )


def test_space_manager_can_create_list_and_withdraw_archive_request(monkeypatch):
    makerspace = space("archive-api-happy")
    actor = manager(makerspace)
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)

    created = client_for(actor).post(
        list_url(makerspace),
        {"reason": "The workshop has permanently closed."},
        format="json",
    )

    assert created.status_code == 201
    archive_request = MakerspaceArchiveRequest.objects.get(pk=created.data["id"])
    assert archive_request.status == MakerspaceArchiveRequest.Status.PENDING
    assert archive_request.requested_by == actor
    assert client_for(actor).get(list_url(makerspace)).data[0]["id"] == archive_request.pk

    withdrawn = client_for(actor).post(withdraw_url(archive_request), format="json")
    assert withdrawn.status_code == 200
    archive_request.refresh_from_db()
    assert archive_request.status == MakerspaceArchiveRequest.Status.WITHDRAWN
    assert archive_request.resolved_by == actor
    assert archive_request.resolved_at is not None
    assert set(
        AuditLog.objects.filter(makerspace=makerspace).values_list("action", flat=True)
    ) >= {
        "makerspace.archive_requested",
        "makerspace.archive_request_withdrawn",
    }


def test_approve_archives_and_decline_keeps_space_live(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    monkeypatch.setattr(archive_requests, "schedule_resolved", lambda _pk: None)
    approver = superadmin()

    approved_space = space("archive-approved")
    approved_request = archive_requests.create(
        approved_space,
        manager(approved_space, "archive-approve-manager"),
        "No longer operating",
    )
    archive_requests.approve(approved_request, approver, "Confirmed with the operator")
    approved_request.refresh_from_db()
    approved_space.refresh_from_db()
    assert approved_request.status == MakerspaceArchiveRequest.Status.APPROVED
    assert approved_request.resolved_at == approved_space.archived_at
    assert approved_space.archived_by == approver

    declined_space = space("archive-declined")
    declined_request = archive_requests.create(
        declined_space,
        manager(declined_space, "archive-decline-manager"),
        "Short closure",
    )
    archive_requests.decline(declined_request, approver, "Use temporary closure instead")
    declined_request.refresh_from_db()
    declined_space.refresh_from_db()
    assert declined_request.status == MakerspaceArchiveRequest.Status.DECLINED
    assert declined_request.resolution_note == "Use temporary closure instead"
    assert declined_space.archived_at is None
    assert AuditLog.objects.filter(
        makerspace=approved_space,
        action="makerspace.archive_request_approved",
    ).exists()
    assert AuditLog.objects.filter(
        makerspace=declined_space,
        action="makerspace.archive_request_declined",
    ).exists()


def test_decline_requires_a_resolution_note(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    makerspace = space("archive-decline-note")
    archive_request = archive_requests.create(
        makerspace,
        manager(makerspace, "archive-decline-note-manager"),
        "Closing",
    )

    with pytest.raises(ValidationError):
        archive_requests.decline(archive_request, superadmin("decline-note-super"), "  ")

    archive_request.refresh_from_db()
    assert archive_request.status == MakerspaceArchiveRequest.Status.PENDING


def test_direct_archive_auto_approves_pending_request(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    monkeypatch.setattr(archive_requests, "schedule_resolved", lambda _pk: None)
    makerspace = space("archive-direct-auto")
    archive_request = archive_requests.create(
        makerspace,
        manager(makerspace, "archive-direct-manager"),
        "Close the space",
    )
    actor = superadmin("archive-direct-super")

    archived = lifecycle.archive(makerspace, actor)

    archive_request.refresh_from_db()
    assert archived.pk == makerspace.pk
    assert archived.archived_at is not None
    assert archive_request.status == MakerspaceArchiveRequest.Status.APPROVED
    assert archive_request.resolved_by == actor
    assert archive_request.resolved_at == archived.archived_at
    assert archive_request.resolution_note == archive_requests.DIRECT_ARCHIVE_NOTE
    assert set(
        AuditLog.objects.filter(makerspace=makerspace).values_list("action", flat=True)
    ) >= {"makerspace.archived", "makerspace.archive_request_approved"}


def test_hidden_space_cannot_request_archival(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    makerspace = space("archive-hidden-request", superadmin_access_enabled=False)
    actor = manager(makerspace, "archive-hidden-manager")

    response = client_for(actor).post(
        list_url(makerspace),
        {"reason": "Close it"},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "superadmin_access_disabled"
    assert not MakerspaceArchiveRequest.objects.filter(makerspace=makerspace).exists()


def test_pending_request_blocks_disabling_superadmin_access(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    makerspace = space("archive-hide-blocked")
    actor = manager(makerspace, "archive-hide-blocked-manager")
    archive_requests.create(makerspace, actor, "Close it")

    response = client_for(actor).patch(
        reverse("admin-makerspace", kwargs={"pk": makerspace.pk}),
        {"superadmin_access_enabled": False},
        format="json",
    )

    assert response.status_code == 400
    assert "withdraw" in str(response.data["superadmin_access_enabled"]).lower()
    makerspace.refresh_from_db()
    assert makerspace.superadmin_access_enabled is True


def test_withdraw_then_recreate_is_limited_by_per_space_cooldown(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    makerspace = space("archive-cooldown")
    first_manager = manager(makerspace, "archive-cooldown-manager-1")
    second_manager = manager(makerspace, "archive-cooldown-manager-2")
    first = archive_requests.create(makerspace, first_manager, "First reason")
    archive_requests.withdraw(first, first_manager)

    with pytest.raises(APIException) as caught:
        archive_requests.create(makerspace, second_manager, "Second reason")

    assert caught.value.detail["code"] == "archive_request_cooldown"
    MakerspaceArchiveRequest.objects.filter(pk=first.pk).update(
        requested_at=timezone.now() - archive_requests.COOLDOWN
    )
    assert archive_requests.create(makerspace, second_manager, "Second reason").pk



def test_a_custom_role_granted_manage_makerspace_can_request_archival(monkeypatch):
    """Authority is the ACTION, not a built-in role name.

    The first implementation gated on `rbac.is_space_manager_identity`, which documents itself
    as deliberately not inferring identity from actions. That refuses a custom role holding
    MANAGE_MAKERSPACE -- the Part L architecture this project runs on, where the five legacy
    roles are editable rows and authority is action-based. A space that renamed or rebuilt its
    administrator role would have been unable to file for its own archival.
    """
    from apps.makerspaces.models import MakerspaceRole

    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    makerspace = space("custom-role-archive")
    role = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name="Administrator",
        slug="administrator",
        granted_actions=["manage_makerspace"],
    )
    actor = user("custom-role-admin", role=User.Role.REQUESTER, is_staff=True)
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    client = APIClient()
    client.force_authenticate(actor)

    response = client.post(
        reverse(
            "admin-makerspace-archive-requests",
            kwargs={"makerspace_id": makerspace.pk},
        ),
        {"reason": "Closing the workshop at the end of the lease."},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert MakerspaceArchiveRequest.objects.filter(
        makerspace=makerspace,
        status=MakerspaceArchiveRequest.Status.PENDING,
    ).exists()
