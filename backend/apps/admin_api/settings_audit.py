"""Which makerspace settings a staff PATCH actually changed, for the audit row.

Audit rows are append-only, so their metadata names the changed FIELDS and never their
values: a secret written through the settings form (bot token, SMTP password, chat
webhook) must not become an undeletable copy, and free text such as a location is not
the audit log's to keep. Names alone still answer "who switched public stats on".
"""

import copy

# Write-only on the serializers and encrypted at rest; comparing them would mean
# decrypting, and the request carrying one is already the change worth recording.
SECRET_FIELDS = frozenset(
    {
        "telegram_bot_token",
        "smtp_password",
        "slack_webhook_url",
        "mattermost_webhook_url",
        "discord_webhook_url",
    }
)
# Not model fields: `public_display_name` lands inside `branding_config`.
DERIVED_FIELDS = {"public_display_name": "branding_config"}


def snapshot(instance, requested):
    """Current values of the model fields a request names, taken before the save."""
    fields = {DERIVED_FIELDS.get(name, name) for name in requested} - SECRET_FIELDS
    # Deep copies: some serializers mutate the instance in place, and a JSON field held
    # by reference would compare equal to itself after the save.
    return {
        name: copy.deepcopy(getattr(instance, name))
        for name in fields
        if hasattr(instance, name)
    }


def changed_fields(before, instance, requested):
    """Sorted names of the fields whose value moved, plus every secret that was sent."""
    moved = {name for name, value in before.items() if getattr(instance, name) != value}
    return sorted(moved | (set(requested) & SECRET_FIELDS))
