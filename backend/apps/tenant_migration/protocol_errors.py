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
