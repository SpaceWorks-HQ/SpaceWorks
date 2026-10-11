from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.events.invites import create_invite
from apps.events.promos import create_promo
from apps.events.ticketing import create_ticket
from tests.events.collab_helpers import make_staff
from tests.events.ticketing_helpers import event_space, account, open_event, signup

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["invite", "promo"])
def test_concurrent_last_code_use_has_one_winner_and_no_orphan_registration(kind):
    space = event_space()
    staff = make_staff(space)
    event = open_event(space, "invite" if kind == "invite" else "accounts")
    users = [account("first"), account("second")]
    if kind == "invite":
        credential, code = create_invite(event, actor=staff, max_uses=1)
        data = {"invite_code": code}
    else:
        ticket = create_ticket(event, actor=staff, name="Paid", amount=10)
        credential, code = create_promo(event, actor=staff, max_uses=1, percent_off=50)
        data = {"promo_code": code, "ticket_type_id": ticket.pk}
    barrier = Barrier(2)

    def redeem(user):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return signup(event, user, **data).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(redeem, users))
    assert sorted(statuses) == [201, 404]
    credential.refresh_from_db()
    assert credential.uses == 1 and event.registrations.count() == 1
