import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import archive_request_notifications, archive_requests, lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceArchiveRequest, MakerspaceMembership

pytestmark = pytest.mark.django_db


def user(username, **overrides):
    values = {
        "email": f"{username}@example.test",
        "access_status": User.AccessStatus.ACTIVE,
    }
    values.update(overrides)
    return User.objects.create_user(username=username, **values)


def manager(makerspace, username):
    actor = user(username, role=User.Role.SPACE_MANAGER, is_staff=True)
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def superadmin(username, *, active=True):
    return user(
        username,
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        is_active=active,
    )


def space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def capture_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        archive_request_notifications,
        "dispatch_email",
        lambda **kwargs: calls.append(kwargs),
    )
    return calls


def test_request_mail_runs_after_commit_for_every_active_superuser_without_reason(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace = space("archive-mail-created")
    actor = manager(makerspace, "archive-mail-manager")
    first = superadmin("archive-mail-super-1")
    second = superadmin("archive-mail-super-2")
    superadmin("archive-mail-inactive", active=False)
    calls = capture_dispatch(monkeypatch)
    reason = "do not broadcast this reason 55cc"

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        archive_requests.create(makerspace, actor, reason)

    assert calls == []
    assert len(callbacks) == 1
    callbacks[0]()
    assert {call["to_email"] for call in calls} == {first.email, second.email}
    assert all(call["makerspace"] is None for call in calls)
    assert all(call["connection"] == "platform" for call in calls)
    assert all("/control/" in call["text_body"] for call in calls)
    assert all(reason not in call["text_body"] for call in calls)


@pytest.mark.parametrize(
    ("transition", "expected_status", "note", "persist_body", "sync"),
    [
        ("approve", MakerspaceArchiveRequest.Status.APPROVED, "", True, False),
        (
            "decline",
            MakerspaceArchiveRequest.Status.DECLINED,
            "Reviewed outcome",
            False,
            True,
        ),
    ],
)
def test_requester_is_mailed_on_manual_outcome(
    monkeypatch,
    django_capture_on_commit_callbacks,
    transition,
    expected_status,
    note,
    persist_body,
    sync,
):
    makerspace = space(f"archive-mail-{transition}")
    requester = manager(makerspace, f"archive-mail-{transition}-manager")
    approver = superadmin(f"archive-mail-{transition}-super")
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    archive_request = archive_requests.create(makerspace, requester, "Close it")
    calls = capture_dispatch(monkeypatch)

    with django_capture_on_commit_callbacks(execute=True):
        if transition == "approve":
            archive_requests.approve(archive_request, approver, note)
        else:
            archive_requests.decline(archive_request, approver, note)

    archive_request.refresh_from_db()
    assert archive_request.status == expected_status
    assert len(calls) == 1
    assert calls[0]["to_email"] == requester.email
    assert calls[0]["makerspace"] is None
    assert calls[0]["persist_body"] is persist_body
    assert calls[0]["sync"] is sync
    if note:
        assert note in calls[0]["text_body"]


def test_direct_archive_auto_approval_mails_requester(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace = space("archive-mail-auto")
    requester = manager(makerspace, "archive-mail-auto-manager")
    approver = superadmin("archive-mail-auto-super")
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    archive_request = archive_requests.create(makerspace, requester, "Close it")
    calls = capture_dispatch(monkeypatch)

    with django_capture_on_commit_callbacks(execute=True):
        lifecycle.archive(makerspace, approver)

    archive_request.refresh_from_db()
    assert archive_request.status == MakerspaceArchiveRequest.Status.APPROVED
    assert len(calls) == 1
    assert calls[0]["to_email"] == requester.email
    assert archive_requests.DIRECT_ARCHIVE_NOTE in calls[0]["text_body"]
    assert calls[0]["persist_body"] is False


def test_smtp_failure_after_commit_never_rolls_back_archive(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace = space("archive-mail-failure")
    requester = manager(makerspace, "archive-mail-failure-manager")
    approver = superadmin("archive-mail-failure-super")
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    archive_request = archive_requests.create(makerspace, requester, "Close it")

    def fail(**_kwargs):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(archive_request_notifications, "dispatch_email", fail)
    with django_capture_on_commit_callbacks(execute=True):
        archived = lifecycle.archive(makerspace, approver)

    archive_request.refresh_from_db()
    archived.refresh_from_db()
    assert archived.archived_at is not None
    assert archive_request.status == MakerspaceArchiveRequest.Status.APPROVED


def test_requester_without_email_is_best_effort_and_does_not_block_resolution(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace = space("archive-mail-no-address")
    requester = manager(makerspace, "archive-mail-no-address-manager")
    requester.email = ""
    requester.save(update_fields=["email"])
    approver = superadmin("archive-mail-no-address-super")
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    archive_request = archive_requests.create(makerspace, requester, "Close it")
    calls = capture_dispatch(monkeypatch)

    with django_capture_on_commit_callbacks(execute=True):
        archive_requests.decline(archive_request, approver, "Not now")

    archive_request.refresh_from_db()
    assert archive_request.status == MakerspaceArchiveRequest.Status.DECLINED
    assert calls == []


def test_audit_transitions_never_retain_reason_or_resolution_text(monkeypatch):
    monkeypatch.setattr(archive_requests, "schedule_created", lambda _pk: None)
    monkeypatch.setattr(archive_requests, "schedule_resolved", lambda _pk: None)
    makerspace = space("archive-audit-text")
    actor = manager(makerspace, "archive-audit-manager")
    reason = "unique private operational reason 9bdf"
    note = "unique resolution note 4a1c"
    archive_request = archive_requests.create(makerspace, actor, reason)
    archive_requests.decline(archive_request, superadmin("archive-audit-super"), note)

    audit_payload = " ".join(
        str(meta)
        for meta in AuditLog.objects.filter(makerspace=makerspace).values_list(
            "meta", flat=True
        )
    )
    assert reason not in audit_payload
    assert note not in audit_payload


def test_a_colleague_withdrawing_notifies_the_requester(monkeypatch):
    """Authority is the ACTION, so another manager can withdraw someone else's request.

    The requester otherwise learns nothing -- their request simply vanishes. Withdrawing your
    own needs no mail, so this asserts both arms: colleague withdrawal notifies, self
    withdrawal stays silent.
    """
    scheduled = []
    monkeypatch.setattr(
        archive_requests, "schedule_created", lambda _pk: None
    )
    monkeypatch.setattr(
        archive_requests, "schedule_resolved", lambda pk: scheduled.append(pk)
    )

    makerspace = space("withdraw-notify")
    author = manager(makerspace, "withdraw-author")
    colleague = manager(makerspace, "withdraw-colleague")

    own = archive_requests.create(makerspace, author, "Closing down.")
    archive_requests.withdraw(own, author)
    assert scheduled == [], "withdrawing your own request should not email you"

    MakerspaceArchiveRequest.objects.filter(pk=own.pk).update(
        requested_at=timezone.now() - archive_requests.COOLDOWN * 2
    )
    second = archive_requests.create(makerspace, author, "Closing down, again.")
    archive_requests.withdraw(second, colleague)

    assert scheduled == [second.pk], "a colleague's withdrawal must notify the requester"
