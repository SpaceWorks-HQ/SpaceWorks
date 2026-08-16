"""Method-aware recovery allowlists; everything absent is refused."""


HEALTH_ROUTES = {
    ("health", "GET"),
    ("health", "HEAD"),
    ("health", "OPTIONS"),
}

QUARANTINE_ALLOWED = HEALTH_ROUTES | {
    ("auth-login", "POST"),
    ("auth-login", "OPTIONS"),
    ("auth-refresh", "POST"),
    ("auth-refresh", "OPTIONS"),
    ("auth-logout", "POST"),
    ("auth-logout", "OPTIONS"),
    ("auth-me", "GET"),
    ("auth-me", "HEAD"),
    ("auth-me", "OPTIONS"),
    ("backup-recovery-state", "GET"),
    ("backup-recovery-state", "HEAD"),
    ("backup-recovery-state", "POST"),
    ("backup-recovery-state", "OPTIONS"),
}

QUIESCED_ALLOWED = HEALTH_ROUTES | {
    ("admin-restore-operation", "GET"),
    ("admin-restore-operation", "HEAD"),
    ("admin-restore-operation", "OPTIONS"),
    ("admin-restore-decision", "POST"),
    ("admin-restore-decision", "OPTIONS"),
}


def route_allowed(mode, view_name, method):
    key = (view_name, method.upper())
    if mode == "quarantined":
        return key in QUARANTINE_ALLOWED
    if mode == "quiesced":
        return key in QUIESCED_ALLOWED
    return True
