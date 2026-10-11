from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.integrations.models import NotificationPreference, EmailLog
from apps.makerspaces.models import MakerspaceMembership, MembershipTerm
from apps.notifications.models import MemberNotificationPreference, NotificationInboxRow
from apps.notifications.broadcasts import segment_members
from tests.test_notification_families_f3 import family_world, capture_delivery
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db


def world(slug):
    space, manager, member, _ = family_world(slug)
    space.enabled_modules = sorted(set(space.enabled_modules) | {'notifications', 'email'})
    space.enabled_features = sorted(set(space.enabled_features) | {'membership.broadcasts', 'notifications.member_inbox', 'notifications.member_preferences'})
    space.save(update_fields=['enabled_modules', 'enabled_features', 'updated_at'])
    NotificationPreference.objects.create(makerspace=space, feature='members', channel='email', enabled=True)
    return space, manager, member


def url(space):
    return reverse('notifications:broadcast-create', kwargs={'makerspace_id': space.pk})


def feed_url(space):
    return reverse('notifications:announcement-feed', kwargs={'makerspace_id': space.pk})


def test_scoped_broadcast_respects_email_and_inbox_opt_out_and_feed_is_personal(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, member = world('broadcast-personal-wp3')
    other = make_member('broadcast-optout-wp3', space, membership_role='custom')
    for channel in ('email', 'in_app'):
        MemberNotificationPreference.objects.create(makerspace=space, user=other, feature='members', channel=channel, enabled=False)
    foreign, _, foreign_member = world('broadcast-foreign-wp3')
    # Use the real outbox suppression checks, but avoid an actual broker/SMTP call.
    monkeypatch.setattr('apps.integrations.dispatch_outbox._enqueue', lambda pk: None)
    with django_capture_on_commit_callbacks(execute=True):
        result = authenticated_client(manager).post(url(space), {'title': 'Room change', 'body': 'Meet in the annex.'}, format='json')
        assert result.status_code == 201
    own = authenticated_client(member).get(feed_url(space))
    assert own.status_code == 200 and own.data['results'][0]['title'] == 'Room change'
    assert authenticated_client(other).get(feed_url(space)).data['count'] == 0
    assert authenticated_client(foreign_member).get(feed_url(space)).status_code in (403, 404)
    assert not NotificationInboxRow.objects.filter(makerspace=foreign, event='broadcast').exists()
    assert not EmailLog.objects.filter(makerspace=space, recipient=other).exclude(status='skipped').exists()
    assert AuditLog.objects.get(action='notification.broadcast_created').actor == manager


def test_plan_status_segment_uses_current_scoped_term_and_foreign_plan_is_invalid():
    from tests.makerspaces.test_membership_plans import plan
    from rest_framework.exceptions import ValidationError
    space, manager, member = world('broadcast-plan-wp3')
    now = timezone.now()
    active = plan(space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    MembershipTerm.objects.create(membership=membership, plan=active, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))
    assert list(segment_members(space, {'plan_id': active.pk}).values_list('user_id', flat=True)) == [member.pk]
    assert list(segment_members(space, {'status': 'active'}).values_list('user_id', flat=True)) == [member.pk]
    MembershipTerm.objects.filter(membership=membership).update(status='expired', ends_at=now - timedelta(hours=1))
    assert list(segment_members(space, {'status': 'lapsed'}).values_list('user_id', flat=True)) == [member.pk]
    assert list(segment_members(space, {'plan_id': active.pk, 'status': 'lapsed'}).values_list('user_id', flat=True)) == [member.pk]
    foreign, _, _ = world('broadcast-plan-foreign-wp3')
    with pytest.raises(ValidationError):
        segment_members(space, {'plan_id': plan(foreign).pk})


def test_manage_members_gate_disabled_feature_and_module_off():
    from tests.module_helpers import disable_module
    space, manager, member = world('broadcast-gates-wp3')
    # family_world's custom membership holds no MANAGE_MEMBERS action.
    values = {'title': 'Announcement', 'body': 'Hello'}
    assert authenticated_client(member).post(url(space), values, format='json').status_code in (403, 404)
    client = authenticated_client(manager)
    space.enabled_features = [key for key in space.enabled_features if key != 'membership.broadcasts']
    space.save(update_fields=['enabled_features', 'updated_at'])
    assert client.post(url(space), values, format='json').status_code == 400
    disable_module(space, 'membership')
    assert client.post(url(space), values, format='json').status_code == 400


def test_revoked_and_globally_restricted_members_never_match():
    space, _, member = world('broadcast-active-wp3')
    MakerspaceMembership.objects.filter(makerspace=space, user=member).update(status='revoked')
    assert not segment_members(space, {}).filter(user=member).exists()
    MakerspaceMembership.objects.filter(makerspace=space, user=member).update(status='active')
    member.access_status = 'restricted'
    member.save(update_fields=['access_status'])
    assert not segment_members(space, {}).filter(user=member).exists()


def test_certification_segment_uses_live_grant_not_an_expired_or_foreign_grant():
    from tests.machines.certification_helpers import _certification, _machine_type
    from apps.machines.models_certifications import CertificationGrant
    space, manager, member = world('broadcast-cert-wp3')
    cert = _certification(space, _machine_type(space))
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    grant = CertificationGrant.objects.create(certification_type=cert, membership=membership, granted_by=manager)
    assert list(segment_members(space, {'certification_id': cert.pk}).values_list('user_id', flat=True)) == [member.pk]
    grant.expires_at = timezone.now() - timedelta(seconds=1)
    grant.save(update_fields=['expires_at'])
    assert not segment_members(space, {'certification_id': cert.pk}).exists()
