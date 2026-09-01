"""Managed-platform fair-use limits; deliberately dormant on self-hosts."""

from apps.makerspaces import domain_verification
from apps.makerspaces.limits_core import (
    BOOLEAN_LIMIT_KEYS,
    KNOWN_LIMIT_KEYS,
    NUMERIC_LIMIT_KEYS,
    RESOURCE_LABELS,
    resource_limit,
)
from apps.makerspaces.limits_reservations import (
    reserve_notification_quota,
    reserve_platform_otp_quota,
    reserve_platform_otp_sms_quota,
)
from apps.makerspaces.limits_usage import (
    _api_clients,
    _assets,
    _bookings,
    _COUNTERS,
    _custom_roles,
    _data_exports,
    _emails,
    _events,
    _machine_service_open,
    _machine_service_submit,
    _machines,
    _members,
    _print_requests,
    _products,
    _staff,
    _storage,
    add_storage,
    check_quota,
    custom_domain_allowed,
    free_storage,
)
from apps.makerspaces.limits_validation import validate_resource_limit_overrides


def is_self_host():
    """Compatibility seam shared by every split limit implementation."""
    return domain_verification.is_self_host()
