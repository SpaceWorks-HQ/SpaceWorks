"""Read-only channel health for monitoring; never bootstrap platform settings."""

from apps.integrations.health import (
    _destinations_section, _email_section, _safe_section, _telegram_section,
)


def _smtp_snapshot(space):
    from apps.integrations.models import PlatformEmailSettings

    if (space.smtp_host or "").strip():
        space.get_smtp_password()
        configured = True
    else:
        row = PlatformEmailSettings.objects.filter(pk=1).first()
        configured = bool(row and (row.smtp_host or "").strip())
        if configured:
            row.get_smtp_password()
    return {"status": "ok", "configured": configured}


def integration_snapshot(space):
    # The general integration-health builder also reads SMS/push configuration via
    # load(), which creates singleton rows. Only these four sections are needed.
    return {
        "email": _safe_section(lambda: _email_section(space)),
        "smtp": _safe_section(lambda: _smtp_snapshot(space)),
        "telegram": _safe_section(lambda: _telegram_section(space)),
        "chat_destinations": _safe_section(lambda: _destinations_section(space)),
    }
