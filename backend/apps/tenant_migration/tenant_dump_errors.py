"""Fail-closed errors raised while deriving a Lane D tenant dump."""


class TenantDumpBuildError(RuntimeError):
    """The sanitized scratch projection cannot be published."""


class TenantDumpDependencyError(TenantDumpBuildError):
    """Incoming rows cannot be loaded with their FK constraints enabled."""


class TenantDumpVerificationError(TenantDumpBuildError):
    """A scratch or restored-dump postcondition did not hold."""
