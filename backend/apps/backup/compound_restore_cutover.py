"""Crash-safe Lane E pointer cutover, acknowledgement, and rollback."""

from .compound_restore_ledger import done_detail, incomplete
from .compound_restore_objects import validate_object_effects
from .compound_restore_types import CompoundRestoreRefused


def journalled_cutover(
    ledger, pointer, database, sibling, *, ownership_proof, grant_state,
    object_effects,
):
    phase = "cutover"
    completed = done_detail(ledger, phase)
    if completed is not None:
        _validate_journal_detail(completed)
        if not pointer.record_matches(completed):
            raise CompoundRestoreRefused("Completed compound cutover pointer changed.")
        _assert_live_candidate(database, sibling, completed)
        return completed
    prior = incomplete(ledger, phase)
    detail = prior["detail"] if prior is not None else {
        **pointer.cutover_detail(sibling),
        "sibling_ownership_proof": ownership_proof,
        "grant_state": grant_state,
        "object_effects": list(object_effects),
    }
    _validate_journal_detail(detail)
    if prior is not None and pointer.record_matches(detail):
        _assert_live_candidate(database, sibling, detail)
        ledger.finish(prior, detail)
        return detail
    begun = prior or ledger.begin(phase, detail)
    pointer.compare_and_swap(detail)
    if not pointer.record_matches(detail):
        raise CompoundRestoreRefused("Compound pointer swap did not commit exactly.")
    _assert_live_candidate(database, sibling, detail)
    ledger.finish(begun, detail)
    return detail


def rollback_cutover(
    ledger, pointer, database, object_store, sibling, *, drop_candidate=False,
):
    cutover = done_detail(ledger, "cutover")
    if cutover is None:
        raise CompoundRestoreRefused("No completed compound cutover exists to roll back.")
    _validate_journal_detail(cutover)
    if drop_candidate and not database.owns(
        sibling, cutover["sibling_ownership_proof"]
    ):
        raise CompoundRestoreRefused("Rollback refuses to drop an unowned database.")
    phase = "rollback"
    completed = done_detail(ledger, phase)
    if completed is not None:
        return completed
    prior = incomplete(ledger, phase)
    detail = prior["detail"] if prior is not None else {
        "old_database_url": cutover["old_database_url"],
        "new_database_url": cutover["new_database_url"],
        "sibling_ownership_proof": cutover["sibling_ownership_proof"],
        "object_effects": cutover["object_effects"],
        "candidate_retained": True,
    }
    begun = prior or ledger.begin(phase, detail)
    if not pointer.record_matches(cutover, rolled_back=True):
        pointer.rollback(cutover)
    if not pointer.record_matches(cutover, rolled_back=True):
        raise CompoundRestoreRefused("Rollback pointer reversal did not commit exactly.")
    created_effects = tuple(
        item for item in cutover["object_effects"]
        if item.get("outcome") == "created_by_this_run"
    )
    reversed_effects = object_store.rollback(created_effects)
    finished = {**detail, "reversed_object_effects": list(reversed_effects)}
    # Ownership evidence is deliberately retained in both cutover and rollback
    # records. Candidate destruction is a separate, ownership-checked operation.
    ledger.finish(begun, finished)
    return finished


def _assert_live_candidate(database, sibling, detail):
    identity = database.query_identity(sibling)
    expected = detail.get("new_database_identity")
    if expected is None or identity.durable_key() != tuple(expected):
        raise CompoundRestoreRefused(
            "The pointer target does not match the queried candidate identity."
        )


def _validate_journal_detail(detail):
    required = {
        "old_database_url", "new_database_url", "old_generation",
        "new_generation", "new_database_identity", "sibling_ownership_proof",
        "grant_state", "object_effects",
    }
    if not isinstance(detail, dict) or not required <= set(detail):
        raise CompoundRestoreRefused("The compound cutover journal is incomplete.")
    if not all(isinstance(detail[name], str) and detail[name] for name in (
        "old_database_url", "new_database_url"
    )):
        raise CompoundRestoreRefused("The compound cutover URLs are missing.")
    if any(
        character in detail[name]
        for name in ("old_database_url", "new_database_url")
        for character in ("\n", "\r", "\x00")
    ):
        raise CompoundRestoreRefused("A compound cutover URL is not journal-safe.")
    old_generation = detail["old_generation"]
    new_generation = detail["new_generation"]
    if (
        type(old_generation) is not int
        or type(new_generation) is not int
        or old_generation < 1
        or new_generation != old_generation + 1
    ):
        raise CompoundRestoreRefused(
            "The compound cutover generation is invalid or non-monotonic."
        )
    identity = detail["new_database_identity"]
    if not isinstance(identity, list) or len(identity) != 5:
        raise CompoundRestoreRefused("The compound candidate identity is incomplete.")
    ownership = detail["sibling_ownership_proof"]
    if (
        not isinstance(ownership, dict)
        or ownership.get("identity") != identity
        or type(ownership.get("created_by_this_run")) is not bool
        or not isinstance(detail["grant_state"], dict)
        or not detail["grant_state"]
    ):
        raise CompoundRestoreRefused(
            "The compound ownership or grant journal is incomplete."
        )
    validate_object_effects(tuple(detail["object_effects"]))
