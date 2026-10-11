from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.integrations import notify
from apps.integrations.models import (
    EmailLog,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationFeature,
    NotificationPreference,
)
from apps.makerspaces import membership_notifications, membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


pytestmark = pytest.mark.django_db


def _user(username):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="password",
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return user


def _space(slug, **kwargs):
    return Makerspace.objects.create(name=slug, slug=slug, **kwargs)


def _role(makerspace, slug):
    return MakerspaceRole.objects.get(makerspace=makerspace, slug=slug)


def _manager(makerspace, username="manager"):
    user = _user(username)
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        assigned_role=_role(makerspace, "space_manager"),
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def test_open_join_sends_member_welcome_email_without_staff_channel_fanout(monkeypatch):
    makerspace = _space(
        "member-welcome", membership_policy=Makerspace.MembershipPolicy.OPEN
    )
    member = _user("member-welcome-user")
    emails = []
    fanout = Mock()

    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.send_makerspace_email",
        lambda *args, **kwargs: emails.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.notify_lifecycle", fanout,
    )

    outcome = membership_services.request_membership(member, makerspace)

    assert outcome["outcome"] == "joined"
    assert NotificationFeature.MEMBERS == "members"
    assert len(emails) == 1
    args, kwargs = emails[0]
    assert args[0] == makerspace
    assert args[3] == [member.email]
    assert kwargs["stream"] == "membership"
    assert kwargs["audience"] == "member"
    assert kwargs["event"] == "joined"
    fanout.assert_called_once()
    assert fanout.call_args.kwargs["feature"] == "members"
    assert fanout.call_args.kwargs["event"] == "member_joined"
    assert fanout.call_args.kwargs["build"]().emails == ()


def test_activation_is_idempotent_and_does_not_duplicate_member_delivery(monkeypatch):
    makerspace = _space(
        "member-idempotent", membership_policy=Makerspace.MembershipPolicy.OPEN
    )
    member = _user("member-idempotent-user")
    email = Mock()
    fanout = Mock()
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.send_makerspace_email", email,
    )
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.notify_lifecycle", fanout,
    )

    first = membership_services.request_membership(member, makerspace)
    second = membership_services.request_membership(member, makerspace)

    assert first["membership_id"] == second["membership_id"]
    assert email.call_count == 1
    assert fanout.call_count == 1


def test_request_policy_emits_the_pending_staff_lifecycle_event(monkeypatch):
    makerspace = _space("member-request-pending")
    applicant = _user("member-request-applicant")
    fanout = Mock()
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.notify_lifecycle", fanout,
    )

    outcome = membership_services.request_membership(applicant, makerspace)

    assert outcome["outcome"] == "requested"
    fanout.assert_called_once()
    assert fanout.call_args.kwargs["feature"] == "members"
    assert fanout.call_args.kwargs["event"] == "request_pending"


def test_verification_sends_a_member_only_email_once(monkeypatch):
    makerspace = _space("member-verified")
    manager = _manager(makerspace)
    member = _user("member-verified-user")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=member,
        assigned_role=_role(makerspace, "member"),
        role=MakerspaceMembership.Role.CUSTOM,
    )
    email = Mock()
    fanout = Mock()
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.send_makerspace_email", email,
    )
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.notify_lifecycle", fanout,
    )

    membership_services.verify_member(manager, membership)
    membership_services.verify_member(manager, membership)

    email.assert_called_once()
    assert email.call_args.kwargs == {
        "stream": "membership", "event": "verified", "audience": "member",
        "recipient_id": member.pk, "feature": "members",
    }
    assert email.call_args.args[3] == [member.email]
    fanout.assert_not_called()


def test_member_staff_alerts_follow_the_matrix_and_makerspace_scope(monkeypatch):
    makerspace = _space("member-staff-alerts")
    manager = _manager(makerspace, "member-staff-manager")
    other_space = _space("member-other-space")
    other_manager = _manager(other_space, "member-other-manager")
    member = _user("member-staff-target")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=member,
        assigned_role=_role(makerspace, "member"),
        role=MakerspaceMembership.Role.CUSTOM,
    )
    emails, channels = [], []
    monkeypatch.setattr(
        notify,
        "dispatch_email",
        lambda **kwargs: emails.append(kwargs) or type("Log", (), {"status": EmailLog.Status.SENT})(),
    )
    monkeypatch.setattr(
        notify,
        "dispatch_channel",
        lambda **kwargs: channels.append(kwargs) or type("Log", (), {"status": NotificationDeliveryStatus.SENT})(),
    )

    membership_notifications.notify_member_joined(membership, sync=True)
    assert emails == [] and channels == []

    NotificationPreference.objects.create(
        makerspace=makerspace,
        feature=NotificationFeature.MEMBERS,
        channel=NotificationChannel.EMAIL,
        enabled=True,
    )
    membership_notifications.notify_member_joined(membership, sync=True)
    assert [call["to_email"] for call in emails] == [manager.email]
    assert other_manager.email not in [call["to_email"] for call in emails]
    assert channels == []

    NotificationPreference.objects.update_or_create(
        makerspace=makerspace,
        feature=NotificationFeature.MEMBERS,
        channel=NotificationChannel.EMAIL,
        defaults={"enabled": False},
    )
    NotificationPreference.objects.create(
        makerspace=makerspace,
        feature=NotificationFeature.MEMBERS,
        channel=NotificationChannel.TELEGRAM,
        enabled=True,
    )
    membership_notifications.notify_member_joined(membership, sync=True)
    assert len(emails) == 1
    assert [call["channel"] for call in channels] == [NotificationChannel.TELEGRAM]


def test_legacy_manager_invitation_email_still_uses_the_membership_stream(monkeypatch):
    makerspace = _space("member-invitation")
    manager = _manager(makerspace)
    email = Mock()
    monkeypatch.setattr("apps.integrations.email.send_makerspace_email", email)

    membership_services.invite_membership(
        manager, makerspace, "invitee@example.test", _role(makerspace, "member")
    )

    email.assert_called_once()
    assert email.call_args.args[3] == ["invitee@example.test"]
    assert email.call_args.kwargs == {
        "stream": "membership", "event": "invitation", "audience": "member",
    }
