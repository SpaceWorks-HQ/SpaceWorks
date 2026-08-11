"""A module purge must never destroy a payment, and a subject-less payment must still work.

Switching a module off and purging its rows is not a reason to destroy the record of money that
really changed hands: a receipt has to stay visible and a pending charge has to stay payable. So no
plan declares payment subjects any more and `module_purge._purge` deletes none.

That leaves payments pointing at a vanished subject, and the dangerous half is the WRITE paths.
`Payment.save()` calls `full_clean()` unconditionally and `clean()` required the subject row to
exist, so before this change hosted checkout created a provider session and then failed persisting
its URL, offline reconciliation raised an untranslated error, and webhook settlement 500'd and rolled
back its idempotency row -- a payment that really settled at Stripe could never be recorded.
"""

from decimal import Decimal

import pytest

from apps.payments.models import Payment
from apps.payments.subjects import resolve_subject_labels, subject_label

pytestmark = pytest.mark.django_db


def make_space(slug):
    from apps.makerspaces.models import Makerspace

    return Makerspace.objects.create(name=slug, slug=slug)


def make_user(username):
    from apps.accounts.models import User

    return User.objects.create_user(
        username=username, email=f"{username}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )


def paid_event_registration(space, member, title="Laser 101"):
    """A real event + registration, so `Payment.clean()` accepts the subject."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.events.models import Event, EventRegistration

    start = timezone.now() + timedelta(hours=1)
    event = Event.objects.create(
        makerspace=space, title=title, status=Event.Status.PUBLISHED,
        starts_at=start, ends_at=start + timedelta(hours=2), is_public=True,
    )
    return EventRegistration.objects.create(
        event=event, member=member, name="Ada", email=member.email, phone="1234567890",
        registered_via_makerspace=space, payment_via_makerspace=space,
    )


def charge(space, member, registration, label="Laser 101", status=None):
    return Payment.objects.create(
        makerspace=space, member=member, created_by=member,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        amount=Decimal("10.00"), currency="usd",
        status=status or Payment.Status.PENDING,
        via_makerspace=space,
        subject_label=label,
    )


def purge_events(space):
    from apps.makerspaces.module_purge_collectors import events_delete

    return events_delete(space, None)


# --- the purge no longer deletes payments -------------------------------------------


def test_a_module_purge_leaves_the_payment_alone():
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    payment = charge(space, member, registration)

    purge_events(space)

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING, "status must not be reset"
    assert Payment.objects.filter(pk=payment.pk).exists()


def test_no_plan_declares_payment_subjects_any_more():
    """The field is gone from the dataclass, so no plan can quietly reintroduce a delete."""
    from apps.makerspaces.module_purge_plans import PLANS, ModulePurgePlan

    assert not hasattr(ModulePurgePlan, "payment_subjects")
    for plan in PLANS:
        assert not hasattr(plan, "payment_subjects"), plan.key


def test_a_terminal_receipt_survives_with_its_status_intact():
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    payment = charge(space, member, registration, status=Payment.Status.PAID_ONLINE)

    purge_events(space)

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_ONLINE, "a paid receipt must stay paid"


# --- the write paths, which is where this actually broke ----------------------------


def test_a_subject_less_payment_can_still_be_saved():
    """The money bug: `save()` -> `full_clean()` -> `clean()` required the subject to exist."""
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    payment = charge(space, member, registration)
    purge_events(space)

    fresh = Payment.objects.get(pk=payment.pk)
    fresh.stripe_checkout_url = "https://checkout.example.test/session"
    fresh.save()  # this raised ValidationError before the clean() fix

    fresh.refresh_from_db()
    assert fresh.stripe_checkout_url == "https://checkout.example.test/session"


def test_a_subject_less_pending_payment_can_still_settle():
    """Webhook settlement. Failing here 500s and rolls back the idempotency row."""
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    payment = charge(space, member, registration)
    purge_events(space)

    fresh = Payment.objects.get(pk=payment.pk)
    fresh.status = Payment.Status.PAID_ONLINE
    fresh.save()

    fresh.refresh_from_db()
    assert fresh.status == Payment.Status.PAID_ONLINE


def test_an_existing_payment_still_cannot_be_repointed_at_a_foreign_subject():
    """The tolerance must be narrow: skipping validation whenever `pk` exists is too broad."""
    from django.core.exceptions import ValidationError

    space, other = make_space("host"), make_space("other")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    foreign = paid_event_registration(other, make_user("outsider"), title="Not yours")
    payment = charge(space, member, registration)

    payment.subject_id = foreign.pk

    with pytest.raises(ValidationError):
        payment.save()


def test_a_new_payment_still_requires_a_real_same_tenant_subject():
    from django.core.exceptions import ValidationError

    space = make_space("host")
    member = make_user("member")

    with pytest.raises(ValidationError):
        Payment.objects.create(
            makerspace=space, member=member, created_by=member,
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            subject_id=999999,
            amount=Decimal("5.00"), currency="usd",
        )


# --- label resolution ----------------------------------------------------------------


def test_the_snapshot_survives_the_purge_and_names_the_event():
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member, title="Laser 101")
    payment = charge(space, member, registration, label="Laser 101")
    purge_events(space)

    payment.refresh_from_db()
    labels = resolve_subject_labels([payment])

    assert subject_label(payment, labels) == "Laser 101"


def test_the_snapshot_wins_over_a_renamed_live_subject():
    """A receipt must say what it was for when issued, not what the event is called today."""
    from apps.events.models import Event

    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member, title="Laser 101")
    payment = charge(space, member, registration, label="Laser 101")
    Event.objects.filter(pk=registration.event_id).update(title="Renamed Entirely")

    labels = resolve_subject_labels([payment])

    assert subject_label(payment, labels) == "Laser 101"


def test_a_legacy_blank_snapshot_falls_back_to_the_live_title():
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member, title="Laser 101")
    payment = charge(space, member, registration, label="")

    labels = resolve_subject_labels([payment])

    assert subject_label(payment, labels) == "Laser 101"


def test_a_blank_snapshot_with_no_subject_still_never_returns_empty():
    """Stripe rejects an empty `product_data.name`, and this feeds the checkout line item."""
    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    payment = charge(space, member, registration, label="")
    purge_events(space)

    payment.refresh_from_db()
    labels = resolve_subject_labels([payment])

    assert subject_label(payment, labels)


def test_a_member_mismatch_is_not_allowed_to_borrow_a_live_title():
    """Live resolution keyed on global pk alone would hand over another member's title."""
    space = make_space("host")
    member, other = make_user("member"), make_user("other")
    registration = paid_event_registration(space, other, title="Someone Else's Class")
    payment = charge(space, member, registration, label="")

    labels = resolve_subject_labels([payment])

    assert subject_label(payment, labels) == payment.get_subject_type_display()


# --- the audit gap -------------------------------------------------------------------


def test_raising_a_charge_is_audited():
    """Only settlement was logged before; the moment a debt is incurred was not."""
    from apps.audit.models import AuditLog
    from apps.payments.services import create_payment
    from tests.payments.test_models import configured_settings

    space = make_space("host")
    member = make_user("member")
    registration = paid_event_registration(space, member)
    settings = configured_settings(space)
    settings.default_currency = "usd"
    settings.save(update_fields=["default_currency"])

    payment = create_payment(
        makerspace=space,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        member=member,
        amount=Decimal("10.00"),
        currency="usd",
        created_by=member,
        subject_label="Laser 101",
    )

    entry = AuditLog.objects.filter(action="payment.created").first()
    assert entry is not None
    assert entry.meta["payment_id"] == payment.pk
    assert entry.meta["amount"] == "10.00"
    # The label is deliberately absent: the audit log is append-only and undeletable.
    assert "subject_label" not in entry.meta

