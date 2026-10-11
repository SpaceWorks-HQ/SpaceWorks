"""F3 sends membership lifecycle mail to the owning account, never staff channels."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.integrations.models import NotificationPreference
from apps.makerspaces.membership_renewal_notifications import notify_term
from apps.makerspaces.models import MakerspaceMembership, MembershipTerm
from tests.makerspaces.test_membership_plans import plan
from tests.test_notification_families_f3 import family_world, capture_delivery

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("event", ["renewal_due", "grace_started", "lapsed", "renewed", "renewal_failed", "cancelled"])
def test_lifecycle_mail_only_reaches_the_terms_owner(monkeypatch, django_capture_on_commit_callbacks, event):
    space, manager, owner, _ = family_world(f"renewal-mail-{event}")
    space.enabled_features = sorted(set(space.enabled_features) | {"membership.lifecycle_mail"})
    space.save()
    NotificationPreference.objects.create(makerspace=space, feature="members", channel="email", enabled=True)
    NotificationPreference.objects.create(makerspace=space, feature="members", channel="telegram", enabled=True)
    membership = MakerspaceMembership.objects.get(user=owner, makerspace=space)
    now = timezone.now()
    term = MembershipTerm.objects.create(membership=membership, plan=plan(space),
                                         starts_at=now, ends_at=now + timedelta(days=30))
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_term(term, event)
        assert emails == []
    assert [message["to_email"] for message in emails] == [owner.email]
    assert manager.email not in [message["to_email"] for message in emails]
    assert channels == []


def test_lifecycle_feature_off_schedules_nothing(monkeypatch, django_capture_on_commit_callbacks):
    space, _, owner, _ = family_world("renewal-mail-off")
    membership = MakerspaceMembership.objects.get(user=owner, makerspace=space)
    now = timezone.now()
    term = MembershipTerm.objects.create(membership=membership, plan=plan(space),
                                         starts_at=now, ends_at=now + timedelta(days=30))
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        notify_term(term, "lapsed")
    assert callbacks == [] and emails == [] and channels == []
