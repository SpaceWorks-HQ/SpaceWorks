"""Replay tombstones must outlive the maximum accepted command age."""

from django.conf import settings
from django.core.checks import Error, register

POSITIVE = (
    "KIOSK_COMMAND_MAX_AGE_SECONDS", "KIOSK_REPLAY_RETENTION_SECONDS",
    "KIOSK_REPLAY_CLAIM_TIMEOUT_SECONDS", "KIOSK_REPLAY_CLEANUP_BATCH_SIZE",
)


@register()
def check_replay_timing(app_configs=None, **kwargs):
    errors = []
    for index, name in enumerate(POSITIVE, 101):
        value = getattr(settings, name, None)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(Error(f"{name} must be a positive integer.", id=f"hardware_requests.E{index}"))
    if errors:
        return errors
    if settings.KIOSK_REPLAY_CLAIM_TIMEOUT_SECONDS >= settings.KIOSK_COMMAND_MAX_AGE_SECONDS:
        errors.append(Error("Replay claim timeout must be less than command max age.", id="hardware_requests.E105"))
    if settings.KIOSK_COMMAND_MAX_AGE_SECONDS > settings.KIOSK_REPLAY_RETENTION_SECONDS:
        errors.append(Error("Replay retention must cover the maximum command age.", id="hardware_requests.E106"))
    return errors
