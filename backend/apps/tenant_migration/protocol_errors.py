class TenantMigrationProtocolError(RuntimeError):
    """Base class for fail-closed cutover protocol errors."""


class PairingError(TenantMigrationProtocolError):
    pass


class ReceiptValidationError(TenantMigrationProtocolError):
    pass


class ReceiptReplayError(TenantMigrationProtocolError):
    pass


class TransitionConflictError(TenantMigrationProtocolError):
    pass


class TenantStateAdapterError(TenantMigrationProtocolError):
    pass


class ClosureAdmissionError(TenantMigrationProtocolError):
    code = "closure_admission_failed"

    def __init__(self, detail, *, model="", edge=""):
        self.model = model
        self.edge = edge
        super().__init__(detail)


class ClosureChangedError(ClosureAdmissionError):
    code = "closure_changed"


class ImportStateError(TenantMigrationProtocolError):
    code = "import_state_conflict"


class MembershipDependencyError(TenantMigrationProtocolError):
    code = "membership_dependency_conflict"
