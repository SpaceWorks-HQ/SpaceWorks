"""The capture-bound money fingerprint (owner decision D5).

Pending charges travel in a portable dump now. The capture freezes the database under
an exclusive gate and then REOPENS the source, so between the freeze and publication the
space can settle a captured debt or raise a new one. Publishing then would hand out an
artifact that bills a member for money the source has already taken.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.payments.models import ManualSettlement, Payment
from apps.tenant_migration.money_digest import (
    MoneyDriftRefused,
    assert_money_unchanged,
    money_fingerprint,
)

pytestmark = pytest.mark.django_db


class _Capture:
    """The two fields `assert_money_unchanged` reads, without a full capture row."""

    def __init__(self, makerspace_id, digest):
        self.source_makerspace_id = makerspace_id
        self.money_fingerprint_sha256 = digest


def _space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def _member(name, space):
    return User.objects.create_user(username=name, email=f"{name}@example.test")


def _pending(space, actor, subject_id):
    # bulk_create to skip `Payment.clean()`, which insists the BOOKING subject really
    # exists in this makerspace. The fingerprint reads status/amount/currency/provider
    # and never resolves a subject, so a synthetic id is faithful here.
    row = Payment(
        makerspace=space,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=subject_id,
        subject_label=f"Synthetic {subject_id}",
        member=actor,
        amount=Decimal("20.00"),
        currency="usd",
        created_by=actor,
    )
    Payment.objects.bulk_create([row])
    return Payment.objects.get(makerspace=space, subject_id=subject_id)


def test_an_untouched_source_matches_its_capture():
    space = _space("money-stable")
    actor = _member("money-stable-actor", space)
    _pending(space, actor, 1)
    capture = _Capture(space.pk, money_fingerprint(space.pk))

    assert assert_money_unchanged(capture) == capture.money_fingerprint_sha256


def test_settling_a_captured_debt_after_the_freeze_refuses_publication():
    """The case that matters: the member already paid at the desk."""
    space = _space("money-settled-after")
    actor = _member("money-settled-after-actor", space)
    payment = _pending(space, actor, 2)
    capture = _Capture(space.pk, money_fingerprint(space.pk))

    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.PAID_OFFLINE)
    ManualSettlement.objects.create(
        payment=payment,
        method=ManualSettlement.Method.CASH,
        received_at=timezone.now(),
        amount=payment.amount,
        currency=payment.currency,
        recorded_by=actor,
    )

    with pytest.raises(MoneyDriftRefused):
        assert_money_unchanged(capture)


def test_raising_a_new_debt_after_the_freeze_refuses_publication():
    space = _space("money-new-after")
    actor = _member("money-new-after-actor", space)
    _pending(space, actor, 3)
    capture = _Capture(space.pk, money_fingerprint(space.pk))

    _pending(space, actor, 4)

    with pytest.raises(MoneyDriftRefused):
        assert_money_unchanged(capture)


def test_a_capture_predating_the_fingerprint_is_not_revalidated():
    """A blank digest means "not recorded", not "nothing was owed".

    Comparing against it would refuse every capture taken before this field existed.
    """
    space = _space("money-legacy-capture")
    actor = _member("money-legacy-actor", space)
    _pending(space, actor, 5)

    assert assert_money_unchanged(_Capture(space.pk, "")) is None


def test_terminal_history_alone_does_not_look_like_drift():
    """Settled charges are immutable, so they cannot move; including them would make
    every ordinary settlement in an unrelated space read as a changed source."""
    space = _space("money-terminal-only")
    actor = _member("money-terminal-actor", space)
    payment = _pending(space, actor, 6)
    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.WAIVED)
    capture = _Capture(space.pk, money_fingerprint(space.pk))

    assert assert_money_unchanged(capture) == capture.money_fingerprint_sha256
