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
