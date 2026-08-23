"""Fail-closed errors raised while deriving a Lane D tenant dump."""


class TenantDumpBuildError(RuntimeError):
    """The sanitized scratch projection cannot be published."""


class TenantDumpDependencyError(TenantDumpBuildError):
    """Incoming rows cannot be loaded with their FK constraints enabled."""


class TenantDumpVerificationError(TenantDumpBuildError):
    """A scratch or restored-dump postcondition did not hold."""


class TenantDumpCustodyError(TenantDumpBuildError):
    """Tenant recipient custody cannot admit or publish this capture."""


class TenantDumpPublicationRefused(TenantDumpBuildError):
    """A frozen lineage can no longer be made discoverable."""
