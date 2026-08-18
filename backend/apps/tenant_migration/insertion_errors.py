"""Typed, non-sensitive failures for target-side tenant insertion."""


class TenantInsertionError(RuntimeError):
    """Base error for raw import infrastructure failures."""


class ImportTransactionRequired(TenantInsertionError):
    """The caller did not provide the all-or-nothing import transaction."""


class TenantImportFenceRequired(TenantInsertionError):
    """A mapped-PII insert was attempted outside its closed import fence."""


class IncompleteImportRow(TenantInsertionError):
    """A raw row omitted a database column or supplied an unknown one."""


class UnsupportedPrimaryKey(TenantInsertionError):
    """A model uses a primary-key strategy the portable importer cannot reserve."""


class PrimaryKeyMapUnavailable(TenantInsertionError):
    """A requested source primary key has no transaction-local mapping."""


class ArchiveFormatError(TenantInsertionError):
    """The decrypted archive is missing data or contains an invalid value."""


class DependencyCycleError(TenantInsertionError):
    """The exported concrete-FK graph cannot be inserted in dependency order."""


class IdentityResolutionError(TenantInsertionError):
    """A retained source identity has no complete target-side decision."""


class ImportVerificationError(TenantInsertionError):
    """The materialized database state does not satisfy the import contract."""


class MaterializationAlreadyCommitted(TenantInsertionError):
    """A competing delivery committed the one-shot database materialization."""


class ImportPromotionInProgress(TenantInsertionError):
    """Another live delivery owns an object-promotion lease."""


class ImportPromotionClaimLost(ImportPromotionInProgress):
    """This delivery was fenced out by a replacement promotion worker."""


class ImportCompletionAuditError(TenantInsertionError):
    """The atomic completion transition could not write its audit entry."""
