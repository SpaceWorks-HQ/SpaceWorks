"""A makerspace that ever refunded a charge must still be purgeable.

`Refund.payment` is PROTECT and the lifecycle purge deleted `Payment` rows without their
refunds first, so the collector raised ProtectedError and the break-glass purge failed for
exactly the spaces that had taken -- and returned -- real money.
"""

import pytest

from apps.accounts.models import User
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.payments.models import ManualSettlement, Payment, Refund
from apps.payments.reconciliation import mark_offline
from tests.payments.test_refunds import paid_deposit, stripe_space
from tests.return_helpers import make_member, settlement_details


@pytest.mark.django_db(transaction=True)
def test_a_space_with_refunds_and_receipts_purges_completely(monkeypatch):
    makerspace, staff = stripe_space(
        "purge-refunded", monkeypatch, [{"id": "re_purge", "status": "succeeded"}]
    )
    paid = paid_deposit(makerspace, staff)
    Refund.objects.create(
        payment=paid, amount=paid.amount, currency=paid.currency,
        provider=paid.provider, created_by=staff, status=Refund.Status.SUCCEEDED,
    )
    member = make_member("purge-refunded-cash", makerspace)
    cash = Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=MakerspaceMembership.objects.get(makerspace=makerspace, user=member).pk,
        member=member, amount="3.00", currency="usd", created_by=member,
    )
    mark_offline(cash, staff, settlement_details())
    actor = User.objects.create_user(
        username="purge-refunded-super", email="purge-refunded-super@example.com",
        role=User.Role.SUPERADMIN, is_staff=True, is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda _keys: None)
    space_id = makerspace.pk

    lifecycle.purge(lifecycle.archive(makerspace, actor), actor)

    assert not Makerspace.objects.filter(pk=space_id).exists()
    assert not Payment.objects.filter(makerspace_id=space_id).exists()
    assert not Refund.objects.filter(payment_id=paid.pk).exists()
    assert not ManualSettlement.objects.filter(payment_id=cash.pk).exists()
