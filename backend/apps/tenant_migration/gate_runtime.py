import logging
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar

from django.db import transaction
from django.utils import timezone

from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.gate_locks import acquire_shared, shared_session
from apps.tenant_migration.models_source_gate import SourceMigrationGate


_archive_authority = ContextVar("source_migration_archive_authority", default=None)
_boundary_session_locks = ContextVar("source_gate_boundary_session_locks", default=())
logger = logging.getLogger(__name__)


def assert_write_allowed(makerspace_id):
    """Lock and validate in either a service transaction or a gate boundary."""
    makerspace_id = int(makerspace_id)
    if transaction.get_connection().in_atomic_block:
        acquire_shared(makerspace_id)
        _assert_gate_state(makerspace_id)
        return
    if makerspace_id in _boundary_session_locks.get():
        _assert_gate_state(makerspace_id)
        return
    # A direct non-transactional assertion is supported for boundary-style callers.
    # Request/task boundaries use ``boundary_tenant_write`` so this same lock remains
    # held after validation and through their entire dispatch.
    with shared_session(makerspace_id):
        _assert_gate_state(makerspace_id)


def _assert_gate_state(makerspace_id):
    gate = SourceMigrationGate.objects.only(
        "state", "owner_id", "fencing_token", "lease_expires_at"
    ).filter(makerspace_id=makerspace_id).first()
    if gate is None or gate.state == SourceMigrationGate.State.OPEN:
        return
    authority = _archive_authority.get()
    if (
        authority == (int(makerspace_id), gate.owner_id, gate.fencing_token)
        and gate.lease_expires_at is not None
        and gate.lease_expires_at > timezone.now()
    ):
        return
    raise SourceMigrationGateClosed(
        "This makerspace is temporarily frozen for tenant migration."
    )


@contextmanager
def boundary_tenant_write(makerspace_id):
    """Validate and hold a session lock without changing dispatch transactions."""
    makerspace_id = int(makerspace_id)
    with shared_session(makerspace_id):
        token = _boundary_session_locks.set(
            _boundary_session_locks.get() + (makerspace_id,)
        )
        try:
            assert_write_allowed(makerspace_id)
            yield
        finally:
            _boundary_session_locks.reset(token)


@contextmanager
def fanout_tenant_write(makerspace_id, *, operation, counts):
    """Hold one tenant boundary, or report a frozen item and let the scan continue."""
    makerspace_id = int(makerspace_id)
    with ExitStack() as stack:
        try:
            stack.enter_context(boundary_tenant_write(makerspace_id))
        except SourceMigrationGateClosed:
            counts["skipped"] = counts.get("skipped", 0) + 1
            logger.info(
                "tenant_fanout_skipped_closed_source_gate",
                extra={"makerspace_id": makerspace_id, "operation": operation},
            )
            yield False
            return
        yield True


def assert_request_write_allowed(request):
    """Late DRF guard for tenants resolved only after parsing/authentication."""
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    from apps.makerspaces.origin_scope import origin_scoped_makerspace_id
    from apps.makerspaces.origin_scope_routes import request_route_targets
    from apps.tenant_migration.gate_policy import HTTP_EXEMPTIONS

    match = getattr(request, "resolver_match", None)
    if getattr(match, "view_name", None) in HTTP_EXEMPTIONS:
        return
    try:
        _name, targets, invalid, _recognized = request_route_targets(request)
    except Exception:
        # Resolution is advisory to the gate. The view remains responsible for
        # deciding whether the route exists and whether its caller is authorized.
        return
    if invalid:
        return
    if len(targets) == 1:
        assert_write_allowed(next(iter(targets)))
        return
    if not targets:
        try:
            makerspace_id = origin_scoped_makerspace_id(request)
        except Exception:
            return
        if isinstance(makerspace_id, int):
            assert_write_allowed(makerspace_id)


@contextmanager
def tenant_write(makerspace_id):
    """Hold the shared advisory lock from validation through transaction commit."""
    with transaction.atomic():
        assert_write_allowed(makerspace_id)
        yield


@contextmanager
def source_archive_write(makerspace_id, owner_id, fencing_token):
    token = _archive_authority.set(
        (int(makerspace_id), owner_id, int(fencing_token))
    )
    try:
        with tenant_write(makerspace_id):
            yield
    finally:
        _archive_authority.reset(token)
