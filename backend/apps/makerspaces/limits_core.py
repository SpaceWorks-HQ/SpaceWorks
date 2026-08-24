from django.conf import settings


NUMERIC_LIMIT_KEYS = frozenset(
    {
        "products",
        "assets",
        "machines",
        "events",
        "bookings",
        "staff",
        "members",
        "storage",
        "print",
        "email",
        "telegram",
        "slack",
        "mattermost",
        "discord",
        "native_push",
        "api_clients",
        "custom_roles",
        "machine_service_open",
        "machine_service_submit",
        "data_exports",
    }
)
BOOLEAN_LIMIT_KEYS = frozenset({"custom_domain"})
KNOWN_LIMIT_KEYS = NUMERIC_LIMIT_KEYS | BOOLEAN_LIMIT_KEYS

RESOURCE_LABELS = {
    "products": "products",
    "assets": "assets",
    "machines": "machines",
    "events": "events",
    "bookings": "active bookings",
    "staff": "staff members",
    "members": "members",
    "storage": "storage",
    "print": "monthly print requests",
    "email": "daily emails",
    "telegram": "daily Telegram notifications",
    "slack": "daily Slack notifications",
    "mattermost": "daily Mattermost notifications",
    "discord": "daily Discord notifications",
    "native_push": "daily native push notifications",
    "api_clients": "API clients",
    "custom_roles": "custom roles",
    "machine_service_open": "open machine service requests",
    "machine_service_submit": "daily machine service requests",
    "data_exports": "active data exports",
    "custom_domain": "custom domains",
}


def resource_limit(makerspace, key) -> int | None:
    """Return the effective managed limit; ``None`` means unlimited."""
    from apps.makerspaces import limits

    if limits.is_self_host():
        return None
    overrides = makerspace.resource_limit_overrides or {}
    if key in overrides:
        value = overrides[key]
        if value is None or value == -1:
            return None
        return int(value)
    return settings.MANAGED_RESOURCE_LIMITS.get(key)
