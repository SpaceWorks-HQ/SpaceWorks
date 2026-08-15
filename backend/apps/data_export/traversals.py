"""Relationship hops that output source paths may cross."""

from .types import Fidelity

# Terminal FK values do not cross a hop: ``actor`` emits ``actor_id``.  Reading a
# related field does, so AuditLog.actor is explicitly granted for actor_username.
TRAVERSALS = {
    Fidelity.REDACTED: frozenset({("audit.AuditLog", "actor")}),
    Fidelity.PORTABLE: frozenset({("audit.AuditLog", "actor")}),
}

NON_TRAVERSABLE = frozenset(
    {
        ("payments.Payment", "via_makerspace"),
        ("events.EventRegistration", "registered_via_makerspace"),
        ("events.EventRegistration", "payment_via_makerspace"),
        ("operations.StockTransfer", "source_makerspace"),
        ("operations.StockTransfer", "destination_makerspace"),
        ("operations.StockTransfer", "source_container"),
        ("operations.StockTransfer", "destination_container"),
        ("events.EventCollaborator", "event"),
    }
)
