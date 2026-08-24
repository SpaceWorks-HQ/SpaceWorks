"""Small idempotence helpers over the shared H1 effect ledger."""


def done_detail(ledger, phase):
    matches = [
        row for row in ledger.records()
        if row["phase"] == phase and row["state"] == "done"
    ]
    return matches[-1]["detail"] if matches else None


def incomplete(ledger, phase):
    rows = ledger.records()
    completed = {
        (row["phase"], row["attempt"])
        for row in rows if row["state"] == "done"
    }
    matches = [
        row for row in rows
        if row["phase"] == phase and row["state"] == "begun"
        and (row["phase"], row["attempt"]) not in completed
    ]
    return matches[-1] if matches else None


def effect(ledger, phase, begun_detail, callback):
    completed = done_detail(ledger, phase)
    if completed is not None:
        return completed
    prior = incomplete(ledger, phase)
    if prior is not None:
        result = callback(prior)
        ledger.finish(prior, result)
        return result
    begun = ledger.begin(phase, begun_detail)
    result = callback(None)
    ledger.finish(begun, result)
    return result
