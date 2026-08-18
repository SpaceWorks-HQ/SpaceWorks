"""Read-only verification for stored audit row MACs.

KNOWN LIMITATION, closed by the next phase. Missing-MAC detection keys off the row's
primary key against its scope's cutover, and the MAC does not bind the id (it is unknown
before insert). An attacker with raw SQL who can bypass the append-only trigger can
therefore rewrite a row's `id` to sit at or below the cutover, clear `row_mac`, and have
the row read as ordinary pre-cutover history. Content edits are still detected, and
forging the cutover itself now requires the master key, so this is a SQL-only attacker
with the ability to rewrite primary keys.

Closing it needs a cutoff that does not depend on mutable row coordinates: the
authenticated batch chain (AuditBatchLeaf binding the id, signed and anchored off-box)
planned for the following phase. Documented rather than silently assumed.
"""

import hmac
from enum import StrEnum

from apps.audit.canonical import AuditCanonicalizationError, calculate_row_mac
from apps.audit.keys import (
    AuditCutoverTampered,
    AuditMacKeyUnavailable,
    attested_from_id,
    audit_mac_configured,
    get_audit_mac_key,
)


class AuditMacStatus(StrEnum):
    """Why three outcomes and not a boolean.

    A row with no MAC is UNATTESTED, which is a legitimate, expected state: history from
    before the attestation cutover, rows written while attestation was switched off, and
    rows brought in by a tenant import all have none. Collapsing that into "invalid" makes
    the verifier cry tampering over normal history, which destroys its usefulness -- the
    only signal that must alarm is MISMATCH.
    """

    ATTESTED = "attested"
    UNATTESTED = "unattested"
    MAC_MISSING = "mac_missing"
    MISMATCH = "mismatch"
    KEY_UNAVAILABLE = "key_unavailable"


def classify_audit_row(row, *, cutover_cache=None) -> AuditMacStatus:
    if row.row_mac is None:
        # No MAC. Legitimate for history from before this scope's cutover, for rows
        # written while attestation was switched off, and for imported rows. But a row
        # ABOVE the cutover should have been sealed, so a missing MAC there is either a
        # stripped MAC or a fail-open incident -- never plain history.
        # One query per scope, not per row: a full history scan is otherwise N+1.
        if cutover_cache is not None and row.makerspace_id in cutover_cache:
            cutover = cutover_cache[row.makerspace_id]
        else:
            try:
                cutover = attested_from_id(row.makerspace_id)
            except AuditCutoverTampered:
                # The cutover itself was edited, which is how a stripped MAC would be
                # hidden. Report tampering rather than trusting the moved boundary.
                return AuditMacStatus.MISMATCH
            except AuditMacKeyUnavailable:
                return AuditMacStatus.KEY_UNAVAILABLE
            if cutover_cache is not None:
                cutover_cache[row.makerspace_id] = cutover
        if cutover is None:
            # No key row for this scope. If attestation is configured that is a
            # provisioning failure or a DELETED TRUST ANCHOR -- never report it clean.
            if audit_mac_configured():
                return AuditMacStatus.KEY_UNAVAILABLE
            return AuditMacStatus.UNATTESTED
        if row.pk > cutover:
            return AuditMacStatus.MAC_MISSING
        return AuditMacStatus.UNATTESTED
    if row.event_uuid is None:
        # A MAC always covers a UUID, so a MAC without one is an impossible state -- and
        # clearing the UUID is exactly how someone would try to launder a tampered row
        # into the "expected history" bucket and make the verifier exit clean.
        return AuditMacStatus.MISMATCH
    try:
        expected = calculate_row_mac(
            get_audit_mac_key(row.makerspace_id),
            makerspace_id=row.makerspace_id,
            event_uuid=row.event_uuid,
            actor_id=row.actor_id,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            meta=row.meta,
            created_at=row.created_at,
        )
    except AuditMacKeyUnavailable:
        # Cannot verify either way; never report this as clean.
        return AuditMacStatus.KEY_UNAVAILABLE
    except AuditCanonicalizationError:
        # The stored payload cannot even be canonicalized, so it cannot be the payload
        # that was signed. That IS a mismatch.
        return AuditMacStatus.MISMATCH
    if hmac.compare_digest(bytes(row.row_mac), expected):
        return AuditMacStatus.ATTESTED
    return AuditMacStatus.MISMATCH


def verify_audit_mac(row, *, cutover_cache=None) -> bool:
    """True only for a row that is attested AND verifies."""
    return (
        classify_audit_row(row, cutover_cache=cutover_cache)
        is AuditMacStatus.ATTESTED
    )
