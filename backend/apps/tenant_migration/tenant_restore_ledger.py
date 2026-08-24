"""Small H1 RunLedger helpers shared by the D7 ordered command."""

from dataclasses import asdict


def records_for(ledger, phase):
    return [record for record in ledger.records() if record["phase"] == phase]


def phase_done(ledger, phase):
    return any(record["state"] == "done" for record in records_for(ledger, phase))


def done_detail(ledger, phase):
    records = [record for record in records_for(ledger, phase) if record["state"] == "done"]
    return records[-1]["detail"] if records else None


def incomplete_effect(ledger, phase):
    records = records_for(ledger, phase)
    done_attempts = {item["attempt"] for item in records if item["state"] == "done"}
    begun = [
        item for item in records
        if item["state"] == "begun" and item["attempt"] not in done_attempts
    ]
    return begun[-1] if begun else None


def ledger_effect(ledger, phase, before, operation):
    if phase_done(ledger, phase):
        return done_detail(ledger, phase)
    begun = ledger.begin(phase, before)
    result = operation()
    detail = result if isinstance(result, dict) else before
    ledger.finish(begun, detail)
    return detail


def sibling_detail(sibling):
    """Ledger a sibling identity without persisting its credential-bearing URL."""
    return {
        "identity": asdict(sibling.identity),
        "empty": sibling.empty,
        "non_routable": sibling.non_routable,
        "created_by_this_run": sibling.created_by_this_run,
        "owner_marker": sibling.owner_marker,
    }
