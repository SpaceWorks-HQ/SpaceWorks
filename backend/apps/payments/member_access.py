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
