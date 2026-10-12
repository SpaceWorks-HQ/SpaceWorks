"""The exact, literal kiosk operation policy (phase 9b).

A kiosk Station never reaches a generic staff URL. Every online operation is one row
here: which Station kinds may run it, which RBAC actions the operator must hold, and
which modules/features must be live. Unknown kinds fail closed. Nothing here grants
authority on its own -- the lease intersects it with the user's current RBAC.
"""

from dataclasses import dataclass

from apps.accounts.rbac_actions import Action


SCANNER = "scanner"
HANDOVER = "handover"
KIOSK_FEATURE = "inventory.kiosk"


@dataclass(frozen=True)
class KioskOperation:
    kind: str
    station_kinds: frozenset
    actions: frozenset
    modules: tuple = ()
    features: tuple = (KIOSK_FEATURE,)


_REVIEWED = ("request_workflow", "evidence_uploads")
_DIRECT_FEATURES = (KIOSK_FEATURE, "inventory.self_checkout")

OPERATIONS = {
    op.kind: op
    for op in (
        KioskOperation(
            "resolve_qr", frozenset({SCANNER, HANDOVER}),
            frozenset({Action.VIEW_INVENTORY}), ("scanner",),
        ),
        KioskOperation(
            "assign_box", frozenset({HANDOVER}),
            frozenset({Action.ASSIGN_BOX}), ("request_workflow",),
        ),
        KioskOperation(
            "reviewed_issue", frozenset({HANDOVER}),
            frozenset({Action.ISSUE_REQUEST, Action.UPLOAD_EVIDENCE}), _REVIEWED,
        ),
        KioskOperation(
            "reviewed_return", frozenset({HANDOVER}),
            frozenset({Action.RETURN_REQUEST, Action.UPLOAD_EVIDENCE}), _REVIEWED,
        ),
        KioskOperation(
            "direct_handout", frozenset({HANDOVER}),
            frozenset({Action.ISSUE_DIRECT_LOAN, Action.UPLOAD_EVIDENCE}),
            ("evidence_uploads",), _DIRECT_FEATURES,
        ),
        KioskOperation(
            "direct_return", frozenset({HANDOVER}),
            frozenset({Action.RETURN_REQUEST, Action.UPLOAD_EVIDENCE}),
            ("evidence_uploads",), _DIRECT_FEATURES,
        ),
    )
}

# Evidence prepare is not a command but needs its own literal row so the lease
# can carry UPLOAD_EVIDENCE only on a handover Station with evidence uploads live.
EVIDENCE_PREPARE = KioskOperation(
    "evidence_prepare", frozenset({HANDOVER}),
    frozenset({Action.UPLOAD_EVIDENCE}), ("evidence_uploads",),
)


def station_kind_actions(station_kind):
    """The widest action set any operation allows on this Station kind."""
    actions = set()
    for operation in (*OPERATIONS.values(), EVIDENCE_PREPARE):
        if station_kind in operation.station_kinds:
            actions |= operation.actions
    return frozenset(actions)


def capabilities_live(makerspace, operation):
    from apps.makerspaces.platform import feature_enabled, module_enabled

    return all(module_enabled(makerspace, key) for key in operation.modules) and all(
        feature_enabled(makerspace, key) for key in operation.features
    )


def operation_permitted(makerspace, station_kind, operation, actions=None):
    if station_kind not in operation.station_kinds:
        return False
    if actions is not None and not operation.actions <= set(actions):
        return False
    return capabilities_live(makerspace, operation)


def permitted_operations(makerspace, station_kind, actions=None):
    """Operation kinds live now for this Station kind (and, optionally, actions)."""
    return sorted(
        kind for kind, operation in OPERATIONS.items()
        if operation_permitted(makerspace, station_kind, operation, actions)
    )


def lease_actions(makerspace, station_kind, effective_actions):
    """Station-kind allow-list ∩ effective RBAC ∩ capability-usable operations."""
    granted = set()
    for operation in (*OPERATIONS.values(), EVIDENCE_PREPARE):
        if operation_permitted(makerspace, station_kind, operation, effective_actions):
            granted |= operation.actions
    return sorted(granted & station_kind_actions(station_kind))
