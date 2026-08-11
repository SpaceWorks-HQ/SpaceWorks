"""Phase 3 -- the host-waiver acceptance's durability: purges, audit, and query cost.

A PROTECT FK on a brand-new column is exactly how a break-glass path stops working without
anybody noticing, so both purges are exercised here directly. And because a purge CLEARS the
acceptance columns, the append-only audit entry is the only record that survives it -- which
makes the audit part of the evidence, not decoration around it.

The acceptance rules themselves live in `test_collaborative_waiver_p14.py`.
"""

import pytest
from django.urls import reverse

from apps.events.models import EventRegistration
from apps.makerspaces.models import MakerspaceWaiver
from tests.events.collab_helpers import (
    client_for,
    collaborate,
    make_event,
    make_member,
    make_space,
)

pytestmark = pytest.mark.django_db


def register_url(space, event):
    return reverse(
        "member-collaborative-event-register",
        kwargs={"makerspace_id": space.pk, "pk": event.pk},
    )


def setup_pair(host_waiver_version=None):
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    waiver = None
    if host_waiver_version is not None:
        waiver = MakerspaceWaiver.objects.create(
            makerspace=host, is_active=True, version=host_waiver_version,
            body="Mind the laser.",
        )
    return host, partner, event, member, waiver


# --- the PROTECT FK must not break either purge --------------------------------------


def test_the_membership_module_purge_is_not_blocked_by_a_held_waiver():
    """A new PROTECT FK is exactly how a break-glass path stops working unnoticed.

    `membership_delete` clears the MEMBERSHIP's three acceptance fields before deleting
    waivers. A registration holding the same waiver has to be cleared in the same step, or
    the module purge raises ProtectedError and the operator cannot purge at all.
    """
    from django.db import connection
    from apps.makerspaces.module_purge_collectors import membership_delete

    host, partner, event, member, waiver = setup_pair("v1")
    client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1", "host_waiver_accepted": True},
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)
    assert registration.host_waiver_id == waiver.pk

    with connection.cursor() as cursor:
        membership_delete(host, cursor)

    registration.refresh_from_db()
    assert registration.host_waiver_id is None
    assert registration.host_waiver_accepted_at is None
    assert registration.host_waiver_version_accepted is None
    assert not MakerspaceWaiver.objects.filter(pk=waiver.pk).exists()


def test_a_registration_hosted_elsewhere_does_not_block_a_full_purge():
    """The registration lives under host A while the waiver belongs to the purged space.

    `lifecycle.purge` only deletes registrations hosted BY the space being purged, so a
    partner-hosted registration holding this space's waiver would survive into the final
    cascade and raise ProtectedError there.
    """
    from django.db import connection

    host, partner, event, member, waiver = setup_pair("v1")
    client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1", "host_waiver_accepted": True},
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)
    assert registration.host_waiver_id == waiver.pk

    # Only the clearing step matters here; the full purge is exercised by its own suite.
    with connection.cursor() as cursor:
        from apps.makerspaces.module_purge_collectors import membership_delete

        membership_delete(host, cursor)

    registration.refresh_from_db()
    assert registration.event.makerspace_id == host.pk
    assert registration.host_waiver_id is None


def test_the_acceptance_is_audited_with_the_version_but_never_the_body():
    """A purge clears the columns; the append-only log is then the only surviving evidence."""
    from apps.audit.models import AuditLog

    host, partner, event, member, waiver = setup_pair("v1")
    client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1", "host_waiver_accepted": True},
        format="json",
    )

    entry = AuditLog.objects.filter(action="event.host_waiver_accepted").latest("id")

    assert entry.makerspace_id == host.pk
    assert entry.meta["host_waiver_id"] == waiver.pk
    assert entry.meta["host_waiver_version"] == "v1"
    assert entry.meta["via_makerspace_id"] == partner.pk
    assert "Mind the laser" not in str(entry.meta)


def test_the_event_list_query_count_does_not_grow_with_the_number_of_events():
    """The property that matters is CONSTANT cost, not an absolute number.

    Resolving the host waiver per row cost one query per event, and repeated identical ones
    when several events shared a host. Counting total queries at two list sizes catches that
    without pinning an exact figure that unrelated work would churn.
    """
    from django.test.utils import CaptureQueriesContext
    from django.db import connection

    host, partner, _, member, _ = setup_pair("v1")
    url = reverse("member-collaborative-events", kwargs={"makerspace_id": partner.pk})
    client = client_for(member)
    client.get(url)

    with CaptureQueriesContext(connection) as one_event:
        assert len(client.get(url).data) == 1

    for index in range(5):
        collaborate(make_event(host, is_public=False, title=f"Extra {index}"), partner)

    with CaptureQueriesContext(connection) as six_events:
        assert len(client.get(url).data) == 6

    assert len(six_events.captured_queries) == len(one_event.captured_queries)


def test_echoing_the_id_and_version_without_accepting_is_refused():
    """A checkbox in one client is not evidence.

    Without an affirmative field at the API boundary, any caller could echo back the visible
    id and version and the backend would persist and audit an acceptance nobody made --
    manufacturing evidence about a real person's agreement, which is worse than storing none.
    """
    _, partner, event, member, waiver = setup_pair("v1")

    response = client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1"},
        format="json",
    )

    assert response.status_code == 400
    assert "host_waiver" in response.data
    assert not EventRegistration.objects.filter(event=event).exists()


def test_explicitly_declining_is_refused():
    _, partner, event, member, waiver = setup_pair("v1")

    response = client_for(member).post(
        register_url(partner, event),
        {
            "host_waiver_id": waiver.pk,
            "host_waiver_version": "v1",
            "host_waiver_accepted": False,
        },
        format="json",
    )

    assert response.status_code == 400


def test_a_retry_can_supply_an_acceptance_an_existing_row_never_had():
    """Every registration written before this column existed is in exactly that state.

    Such a row has a working check-in QR and no recorded agreement, and if the idempotent
    branch returns early without stamping, the member has no way to ever correct it.
    """
    from apps.audit.models import AuditLog

    host, partner, event, member, waiver = setup_pair("v1")
    # A registration that predates the acceptance columns.
    registration = EventRegistration.objects.create(
        event=event, member=member, name=member.display_name, email=member.email,
        phone="1234567890", registered_via_makerspace=partner,
    )
    assert registration.host_waiver_id is None

    response = client_for(member).post(
        register_url(partner, event),
        {
            "host_waiver_id": waiver.pk,
            "host_waiver_version": "v1",
            "host_waiver_accepted": True,
        },
        format="json",
    )

    assert response.status_code == 201
    registration.refresh_from_db()
    assert registration.host_waiver_id == waiver.pk
    assert registration.host_waiver_version_accepted == "v1"
    assert AuditLog.objects.filter(action="event.host_waiver_accepted").exists()


def test_re_accepting_the_same_current_waiver_does_not_duplicate_the_audit():
    from apps.audit.models import AuditLog

    _, partner, event, member, waiver = setup_pair("v1")
    payload = {
        "host_waiver_id": waiver.pk,
        "host_waiver_version": "v1",
        "host_waiver_accepted": True,
    }
    client = client_for(member)
    client.post(register_url(partner, event), payload, format="json")
    before = AuditLog.objects.filter(action="event.host_waiver_accepted").count()

    client.post(register_url(partner, event), payload, format="json")

    assert AuditLog.objects.filter(action="event.host_waiver_accepted").count() == before


# --- a legacy row must not carry a working admission code -----------------------------


def test_a_collaborative_registration_without_acceptance_gets_no_qr():
    """The row shape that exists between shipping collaboration and shipping the waiver."""
    host, partner, event, member, _ = setup_pair("v1")
    legacy = EventRegistration.objects.create(
        event=event, member=member, name=member.display_name, email=member.email,
        phone="1234567890", registered_via_makerspace=partner,
    )

    response = client_for(member).get(
        reverse(
            "member-event-checkin-qr",
            kwargs={"makerspace_id": partner.pk, "pk": legacy.pk},
        )
    )

    assert response.status_code == 404


def test_re_accepting_restores_the_qr():
    """The member can repair their own legacy row; nobody is stranded."""
    host, partner, event, member, waiver = setup_pair("v1")
    EventRegistration.objects.create(
        event=event, member=member, name=member.display_name, email=member.email,
        phone="1234567890", registered_via_makerspace=partner,
    )
    client = client_for(member)
    client.post(
        register_url(partner, event),
        {
            "host_waiver_id": waiver.pk,
            "host_waiver_version": "v1",
            "host_waiver_accepted": True,
        },
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)

    response = client.get(
        reverse(
            "member-event-checkin-qr",
            kwargs={"makerspace_id": partner.pk, "pk": registration.pk},
        )
    )

    assert response.status_code == 200


def test_a_superseded_acceptance_still_yields_a_qr():
    """Deliberately NOT gated on the current version.

    A host revising its waiver after someone registered must not silently void a legitimate
    member's code and turn them away at a door they signed up for, over text they never had
    the chance to read. The gate is "some acceptance", not "the latest".
    """
    host, partner, event, member, waiver = setup_pair("v1")
    client = client_for(member)
    client.post(
        register_url(partner, event),
        {
            "host_waiver_id": waiver.pk,
            "host_waiver_version": "v1",
            "host_waiver_accepted": True,
        },
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)
    waiver.is_active = False
    waiver.save(update_fields=["is_active"])
    MakerspaceWaiver.objects.create(
        makerspace=host, is_active=True, version="v2", body="Also mind the saw.",
    )

    response = client.get(
        reverse(
            "member-event-checkin-qr",
            kwargs={"makerspace_id": partner.pk, "pk": registration.pk},
        )
    )

    assert response.status_code == 200


def test_a_hosts_own_member_is_unaffected_by_the_gate():
    host, _, event, _, _ = setup_pair("v1")
    own = make_member(host, "insider")
    registration = EventRegistration.objects.create(
        event=event, member=own, name="Insider", email=own.email,
        phone="1234567890", registered_via_makerspace=host,
    )

    response = client_for(own).get(
        reverse(
            "member-event-checkin-qr",
            kwargs={"makerspace_id": host.pk, "pk": registration.pk},
        )
    )

    assert response.status_code == 200
