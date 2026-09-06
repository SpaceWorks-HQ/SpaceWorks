"""Payments-only member access for charges that outlive makerspace archival.

Archived spaces remain closed to ordinary member activity, but hiding receipts or
blocking an existing debt would strand money that may already have moved. This narrow
exception therefore lives in payments and must not become a general archived-space gate.
"""

from apps.makerspaces.member_activity_service import active_member_memberships


def member_payment_memberships(user):
    """Active memberships whose payment surfaces may be used, archived spaces included.

    Delegates the identity predicate rather than restating it. Restating it once produced two
    copies of the same five-part security check in two apps, which is precisely the drift
    nobody notices until an audit compares them.
    """
    return active_member_memberships(user)


def member_payment_actor(user, makerspace_id):
    """The membership that may see and settle THIS member's charges, archived or not."""
    return member_payment_memberships(user).filter(makerspace_id=makerspace_id).first()


def member_may_see_own_charges(user, makerspace_id):
    """Whether this caller may see the charges they themselves owe here.

    An active membership is the ordinary answer, but it cannot be the only one. A loan
    deposit or late fee is raised against a BORROWER, and borrowing needs an active
    account -- not a membership -- so an account-only borrower was told "an active
    membership is required" about a debt in their own name, with no way to read the
    amount or see that staff had settled it.

    Deliberately narrow in three ways, because widening a money surface is exactly where
    a security check gets quietly lost:

    * the account itself must still be live and unrestricted -- the same clauses
      `active_member_memberships` applies, so a suspended or restricted user gains
      nothing here;
    * it only admits a caller who holds NO membership in this makerspace. If they hold
      one, its status decides, so a REVOKED member is still refused -- that is a
      deliberate existing contract and not mine to reverse;
    * ownership is read through `member_payment_queryset`, already filtered to
      `member=user`, so it can only ever admit someone to their own money.
    """
    from apps.makerspaces.models import MakerspaceMembership

    if member_payment_actor(user, makerspace_id) is not None:
        return True
    if not (
        user
        and user.is_authenticated
        and user.pk
        and user.is_active
        and user.access_status == user.AccessStatus.ACTIVE
    ):
        return False
    if MakerspaceMembership.objects.filter(
        user=user, makerspace_id=makerspace_id
    ).exists():
        # A membership exists but did not qualify above, so it is revoked, pending or
        # otherwise inactive. That answer stands.
        return False
    from apps.payments.member_scope import member_payment_queryset

    return member_payment_queryset(user, makerspace_id).exists()
