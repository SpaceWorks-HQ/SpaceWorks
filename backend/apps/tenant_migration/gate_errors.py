class SourceMigrationGateError(RuntimeError):
    """Base class for typed source-gate failures."""


class SourceMigrationGateClosed(SourceMigrationGateError):
    """A tenant mutation was refused while its source is frozen."""

    code = "tenant_migration_quiesced"

    def __init__(self, message, *, purpose=None):
        super().__init__(message)
        self.purpose = purpose


class SourceMigrationOwnershipError(SourceMigrationGateError):
    """An owner, fencing token, or lease no longer grants authority."""

    code = "tenant_migration_stale_owner"


class SourceMigrationRecoveryError(SourceMigrationGateError):
    """A recovery attempt could not prove that reopening is safe."""

    code = "tenant_migration_recovery_refused"
