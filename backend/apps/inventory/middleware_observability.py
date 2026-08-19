import logging


WOULD_REJECT_EVENT = "api_client_auth_would_reject"

NO_CREDENTIALS = "no credentials"
UNKNOWN_CLIENT = "unknown client"
BAD_SIGNATURE = "bad signature"
SKEW = "skew"
NONCE_MISSING = "nonce missing"
NONCE_REPLAY = "nonce replay"
SCOPE_DENIED = "scope denied"
TARGET_UNRESOLVED = "target unresolved"
TENANT_MISMATCH = "tenant mismatch"
ORIGIN_DENIED = "origin denied"

_FAILURE_ATTRIBUTE = "_api_client_failure_reason"
_LOGGED_ATTRIBUTE = "_api_client_would_reject_logged"
logger = logging.getLogger("apps.inventory.middleware")


def set_failure_reason(request, reason):
    setattr(request, _FAILURE_ATTRIBUTE, reason)


def scope_failure_reason(observation, client):
    """Name the reason enforcement would reject, distinguishing tenancy from scope.

    A global route that ADMITS tenant apps can still fail purely on scopes -- a
    `public:write` client reading the global makerspace directory, say. Reporting that as
    a tenant mismatch would hide the real problem from exactly the telemetry an operator
    reads before flipping enforcement on, so admission is consulted before falling back
    to a scope denial.
    """
    from apps.apiclients import scope_registry

    if observation.target_resolution == "no_registry_entry":
        return TARGET_UNRESOLVED
    if observation.target_resolved is False:
        return TARGET_UNRESOLVED
    client_tenant = getattr(client, "makerspace_id", None)
    if client_tenant is not None:
        entry = scope_registry.lookup(observation.view_name, observation.method)
        if observation.target_resolution == "global":
            if entry is not None and entry.tenant_apps_admitted:
                return SCOPE_DENIED
            return TENANT_MISMATCH
        if observation.target_makerspace_id != client_tenant:
            return TENANT_MISMATCH
    return SCOPE_DENIED


def log_would_reject(request):
    # OPTIONS is exempt from rejection whatever the flag says (`_should_reject_invalid`
    # returns False for it), so logging it would manufacture readiness warnings for
    # traffic enforcement would never touch.
    if request.method.upper() == "OPTIONS":
        return
    if getattr(request, _LOGGED_ATTRIBUTE, False):
        return
    setattr(request, _LOGGED_ATTRIBUTE, True)
    origin = request.headers.get("Origin")
    logger.warning(
        WOULD_REJECT_EVENT,
        extra={
            "view_name": _view_name(request),
            "method": request.method.upper(),
            "client_id": request.headers.get("X-Client-Id") or None,
            "hmac_credentials_present": any(
                bool(request.headers.get(name))
                for name in ("X-Timestamp", "X-Signature", "X-Nonce")
            ),
            "origin_present": origin is not None,
            "origin": origin,
            "reason": getattr(request, _FAILURE_ATTRIBUTE, NO_CREDENTIALS),
        },
    )


def _view_name(request):
    from apps.apiclients.scope_registry import resolve_view_name

    return resolve_view_name(request)
