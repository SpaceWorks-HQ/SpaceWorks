from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.serializers import ValidationError

from apps.audit.models import AuditLog
from apps.bookings import notifications, services
from apps.bookings.exceptions import BookingConflict, BookingInvalidTransition
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def makerspace(slug='booking-j2', **values):
    return Makerspace.objects.create(name=slug, slug=slug, **values)


def space(tenant=None, mode=BookableSpace.ApprovalMode.INSTANT, **values):
    defaults = {
        'makerspace': tenant or makerspace(),
        'name': 'Workshop',
        'is_public': True,
        'approval_mode': mode,
    }
    defaults.update(values)
    return BookableSpace.objects.create(**defaults)


def book(target, start=None, **values):
    start = start or timezone.now() + timedelta(hours=2)
    defaults = {
        'name': 'Ada',
        'email': 'ada@example.com',
        'phone': '123',
        'starts_at': start,
        'ends_at': start + timedelta(hours=1),
    }
    defaults.update(values)
    # Worker-thread connections don't share the setup transaction's provisioning,
    # so seed the required persistent tenant write-fence row (idempotent).
    from apps.encryption.models import PiiMakerspaceWriteFence
    PiiMakerspaceWriteFence.objects.get_or_create(makerspace_id=target.makerspace_id)
    return services.create_booking(target, **defaults)


def pending(target, start=None, **values):
    start = start or timezone.now() + timedelta(hours=1)
    defaults = {
        'space': target,
        'name': 'Ada',
        'email': 'ada@example.com',
        'phone': '123',
        'starts_at': start,
        'ends_at': start + timedelta(hours=1),
        'status': Booking.Status.PENDING,
    }
    defaults.update(values)
    return Booking.objects.create(**defaults)


def test_instant_and_approval_modes_have_distinct_overlap_behavior():
    start = timezone.now() + timedelta(hours=2)
    instant = space(makerspace('booking-j2-instant'))
    assert book(instant, start).status == Booking.Status.CONFIRMED
    with pytest.raises(BookingConflict):
        book(instant, start + timedelta(minutes=15))

    approval = space(
        makerspace('booking-j2-approval'),
        BookableSpace.ApprovalMode.APPROVE,
    )
    first = book(approval, start)
    second = book(approval, start + timedelta(minutes=15))
    assert first.status == second.status == Booking.Status.PENDING
    assert services.approve_booking(
        first, actor=None
    ).status == Booking.Status.CONFIRMED
    with pytest.raises(BookingConflict):
        services.approve_booking(second, actor=None)
    second.refresh_from_db()
    assert second.status == Booking.Status.PENDING
    cancelled = services.cancel_booking(second, actor=None)
    assert cancelled.status == Booking.Status.CANCELLED
    assert AuditLog.objects.get(action='booking.cancelled').target_id == str(second.pk)
    with pytest.raises(BookingInvalidTransition):
        services.cancel_booking(cancelled, actor=None)


def test_approval_and_rejection_revalidate_state_and_audit_transitions():
    target = space(
        makerspace('booking-j2-lifecycle'),
        BookableSpace.ApprovalMode.APPROVE,
    )
    approved = book(target)
    rejected = book(target, start=approved.ends_at)
    services.approve_booking(approved, actor=None)
    services.reject_booking(rejected, actor=None)

    approved_log = AuditLog.objects.get(action='booking.approved')
    rejected_log = AuditLog.objects.get(action='booking.rejected')
    assert approved_log.meta == {
        'booking_id': approved.pk,
        'old_status': Booking.Status.PENDING,
        'new_status': Booking.Status.CONFIRMED,
    }
    assert rejected_log.meta == {
        'booking_id': rejected.pk,
        'old_status': Booking.Status.PENDING,
        'new_status': Booking.Status.REJECTED,
    }
    for row, operation in (
        (approved, services.approve_booking),
        (rejected, services.reject_booking),
    ):
        with pytest.raises(BookingInvalidTransition):
            operation(row, actor=None)


def test_reject_can_close_stale_request_but_approve_requires_active_future_space():
    target = space(makerspace('booking-j2-stale'))
    future = pending(target)
    ended = pending(
        target,
        starts_at=timezone.now() - timedelta(hours=2),
        ends_at=timezone.now() - timedelta(hours=1),
        email='ended@example.com',
    )
    target.is_active = False
    target.save(update_fields=['is_active'])
    with pytest.raises(BookingInvalidTransition):
        services.approve_booking(future, actor=None)
    assert services.reject_booking(
        ended, actor=None
    ).status == Booking.Status.REJECTED


def test_create_canonicalizes_answers_against_the_locked_space_schema():
    target = space(
        makerspace('booking-j2-answers'),
        custom_form=[
            {
                'id': 'purpose',
                'label': ' Purpose ',
                'type': 'short_text',
                'options': [],
                'required': True,
            }
        ],
    )
    created = book(target, custom_answers={'purpose': '  Build a robot  '})
    assert created.custom_answers == {
        'version': 1,
        'answers': [
            {
                'id': 'purpose',
                'label': 'Purpose',
                'type': 'short_text',
                'value': 'Build a robot',
            }
        ],
    }
    with pytest.raises(ValidationError):
        book(target, start=created.ends_at, custom_answers={})


def test_booking_quota_is_dormant_self_host_and_enforced_managed(monkeypatch):
    tenant = makerspace(
        'booking-j2-quota',
        resource_limit_overrides={'bookings': 1},
    )
    first_space = space(tenant)
    second_space = space(tenant, name='Studio')
    monkeypatch.setattr(limits, 'is_self_host', lambda: True)
    booking_counter = limits._COUNTERS['bookings']
    monkeypatch.setitem(
        limits._COUNTERS,
        'bookings',
        lambda _tenant: (_ for _ in ()).throw(AssertionError('counted')),
    )
    assert book(first_space).status == Booking.Status.CONFIRMED

    monkeypatch.setattr(limits, 'is_self_host', lambda: False)
    monkeypatch.setitem(limits._COUNTERS, 'bookings', booking_counter)
    calls = []
    monkeypatch.setattr(
        notifications,
        'notify_booking_status',
        lambda booking, event: calls.append((booking.pk, event)),
    )
    before_audits = AuditLog.objects.filter(action='booking.created').count()
    with pytest.raises(ValidationError) as caught:
        book(second_space)
    assert caught.value.get_codes() == {'limit': 'limit_reached'}
    assert Booking.objects.filter(space__makerspace=tenant).count() == 1
    assert AuditLog.objects.filter(
        action='booking.created'
    ).count() == before_audits
    assert calls == []


@pytest.mark.parametrize('operation', ('approve', 'reject'))
def test_approval_audit_failure_rolls_back_transition(monkeypatch, operation):
    target = space(
        makerspace(f'booking-j2-audit-{operation}'),
        BookableSpace.ApprovalMode.APPROVE,
    )
    row = book(target)
    monkeypatch.setattr(
        services.audit,
        'record',
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()),
    )
    mutate = (
        services.approve_booking
        if operation == 'approve'
        else services.reject_booking
    )
    with pytest.raises(RuntimeError):
        mutate(row, actor=None)
    row.refresh_from_db()
    assert row.status == Booking.Status.PENDING


@pytest.mark.django_db(transaction=True)
def test_concurrent_overlapping_approvals_have_one_winner():
    target = space(
        makerspace('booking-j2-approval-race'),
        BookableSpace.ApprovalMode.APPROVE,
    )
    start = timezone.now() + timedelta(hours=2)
    rows = (
        book(target, start, email='one@example.com'),
        book(target, start, email='two@example.com'),
    )
    gate = Barrier(2)

    def approve(row):
        close_old_connections()
        gate.wait()
        try:
            services.approve_booking(
                Booking.objects.get(pk=row.pk), actor=None
            )
            return 'approved'
        except BookingConflict:
            return 'conflict'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, rows)) == ['approved', 'conflict']
    assert Booking.objects.filter(
        pk__in=[row.pk for row in rows],
        status=Booking.Status.CONFIRMED,
    ).count() == 1


@pytest.mark.django_db(transaction=True)
def test_managed_quota_serializes_creates_across_spaces(monkeypatch):
    monkeypatch.setattr(limits, 'is_self_host', lambda: False)
    tenant = makerspace(
        'booking-j2-quota-race',
        resource_limit_overrides={'bookings': 1},
    )
    spaces = (space(tenant), space(tenant, name='Studio'))
    gate = Barrier(2)

    def create(target):
        close_old_connections()
        gate.wait()
        try:
            book(BookableSpace.objects.get(pk=target.pk))
            return 'created'
        except ValidationError:
            return 'limited'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, spaces)) == ['created', 'limited']
    assert Booking.objects.filter(space__makerspace=tenant).count() == 1
