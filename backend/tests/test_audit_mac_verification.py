"""Verification/classification behaviour for audit row MACs.

Split out of test_audit_macs.py to stay inside the repository's ~300-line ceiling. This
module owns the question "what does the verifier SAY about a row", including every way a
MAC can be removed or a row laundered into looking like ordinary history.
"""

import pytest
from django.db import connection

from apps.audit.models import AuditLog, AuditMacKey
from apps.audit.keys import advance_attestation_cutover
from apps.audit.services import record
from apps.audit.verification import AuditMacStatus, classify_audit_row
from tests.audit_mac_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def test_pre_cutover_history_is_not_reported_as_a_mismatch():
    """A row at or below its scope's cutover is genuine history, not tampering.

    This is the case the verifier must stay quiet about, or operators learn to ignore it.
    """
    actor = make_user("audit-mac-history")
    makerspace = make_space("audit-mac-history")
    row = record(actor, "audit.history", makerspace=makerspace)

    # Advance the cutover the legitimate way, which re-stamps its MAC. Editing the
    # column directly is the attack, covered separately below.
    advance_attestation_cutover(makerspace.pk)
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            "UPDATE audit_auditlog SET row_mac = NULL, event_uuid = NULL WHERE id = %s",
            [row.pk],
        )
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.UNATTESTED


def test_stripping_both_columns_after_the_cutover_is_still_detected():
    actor = make_user("audit-mac-unattested")
    makerspace = make_space("audit-mac-unattested")
    row = record(actor, "audit.attested", makerspace=makerspace)
    assert classify_audit_row(row) is AuditMacStatus.ATTESTED

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            "UPDATE audit_auditlog SET row_mac = NULL, event_uuid = NULL WHERE id = %s",
            [row.pk],
        )
    row.refresh_from_db()
    assert classify_audit_row(row) is AuditMacStatus.MAC_MISSING


def test_tampered_row_is_reported_as_a_mismatch():
    actor = make_user("audit-mac-tampered")
    row = record(actor, "audit.before")

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            "UPDATE audit_auditlog SET action = %s WHERE id = %s",
            ["audit.after", row.pk],
        )
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.MISMATCH


def test_half_attested_row_is_a_mismatch_not_history():
    """Clearing event_uuid must not launder a tampered row into "unattested".

    A MAC always covers a UUID, so mac-without-uuid is impossible for a legitimate row.
    Classifying it as history would let verify_audit_macs exit 0 on real corruption.
    """
    actor = make_user("audit-mac-half-attested")
    row = record(actor, "audit.half")
    assert classify_audit_row(row) is AuditMacStatus.ATTESTED

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            "UPDATE audit_auditlog SET event_uuid = NULL WHERE id = %s", [row.pk]
        )
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.MISMATCH


def test_switching_attestation_off_on_an_attested_scope_is_flagged(settings):
    """Turning attestation off AFTER a scope has a key must not be silent.

    Without the master key the scope's cutover cannot be verified either, so the honest
    answer is KEY_UNAVAILABLE rather than MAC_MISSING -- we cannot tell whether the row
    should have been sealed. Both fail verification, which is the property that matters:
    a deployment cannot claim to attest and then quietly stop.
    """
    settings.AUDIT_MAC_MASTER_KEY = ""
    row = record(make_user("audit-mac-off-uuid"), "audit.off_uuid")

    assert row.row_mac is None
    assert row.event_uuid is not None
    assert classify_audit_row(row) is AuditMacStatus.KEY_UNAVAILABLE


def test_stripping_the_mac_from_an_attested_row_is_detected():
    """`UPDATE ... SET row_mac = NULL` must not launder a row into "history".

    This is the cheapest possible attack on the whole feature, so it is the one that most
    needs a test: the scope's cutover id proves the row should have been sealed.
    """
    actor = make_user("audit-mac-stripped")
    makerspace = make_space("audit-mac-stripped")
    row = record(actor, "audit.sealed", makerspace=makerspace)
    assert classify_audit_row(row) is AuditMacStatus.ATTESTED

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            "UPDATE audit_auditlog SET row_mac = NULL WHERE id = %s", [row.pk]
        )
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.MAC_MISSING



def test_advancing_the_cutover_without_its_mac_is_detected():
    """Stripping a MAC and moving the cutover past the row must not read as clean.

    The cutover is what makes a missing MAC detectable, so an unauthenticated integer
    would just relocate the attack one column to the left.
    """
    actor = make_user("audit-mac-cutover-forge")
    makerspace = make_space("audit-mac-cutover-forge")
    row = record(actor, "audit.sealed", makerspace=makerspace)

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        cursor.execute(
            "UPDATE audit_auditlog SET row_mac = NULL WHERE id = %s", [row.pk]
        )
    # Forge the boundary directly, leaving attested_from_mac stale.
    AuditMacKey.objects.filter(makerspace=makerspace).update(attested_from_id=row.pk)
    row.refresh_from_db()

    assert classify_audit_row(row) is AuditMacStatus.MISMATCH


def test_a_cached_key_does_not_survive_removing_the_master_key(settings):
    """Switching attestation off must bite a WARM process, not just a cold one.

    `get_audit_mac_key` caches the unwrapped key. If the cache were consulted before the
    configured check, a running process would keep verifying with the cached key after
    the operator removed AUDIT_MAC_MASTER_KEY -- while `record()`, which asks per write,
    had already started storing NULL MACs. The verifier would then accuse the deployment
    of stripping MACs it never wrote.
    """
    from apps.audit.keys import AuditMacKeyUnavailable, get_audit_mac_key

    makerspace = make_space("audit-mac-warm-cache")
    attested = record(make_user("audit-mac-warm-cache-user"), "audit.warm", makerspace=makerspace)
    assert classify_audit_row(attested) is AuditMacStatus.ATTESTED
    # The key is now cached for this scope.

    settings.AUDIT_MAC_MASTER_KEY = ""

    with pytest.raises(AuditMacKeyUnavailable):
        get_audit_mac_key(makerspace.pk)
    assert classify_audit_row(attested) is AuditMacStatus.KEY_UNAVAILABLE
