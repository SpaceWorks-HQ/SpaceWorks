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


class TenantDumpClosureRefused(TenantDumpVerificationError):
    """The immutable image cannot produce a total full-user/stub closure."""

    def __init__(self, detail, *, reason_code="closure_refused", closure=None):
        self.reason_code = reason_code
        self.closure = closure
        super().__init__(detail)


class TenantDumpDispositionRefused(TenantDumpBuildError):
    """A cross-tenant or payment row has no truthful D6 projection."""

    def __init__(self, detail, *, reason_code="disposition_refused"):
        self.reason_code = reason_code
        super().__init__(detail)
