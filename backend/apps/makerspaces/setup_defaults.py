"""Sensible initial settings for non-interactive area installs; never reset old areas."""
APPLICATION_FORM = [{"id": "reason", "label": "Why would you like to join?",
                     "type": "paragraph", "required": True, "options": []}]
QUIET_CHANNELS = ["email", "telegram", "slack", "mattermost", "discord", "native_push", "webhook"]


def initial_settings(configuring, supplied, *, first_setup=False, stored_currency=None):
    defaults = {}
    if "inventory" in configuring:
        defaults["loan_policy"] = {"loan_max_active": 0, "loan_max_items": 0,
                                   "default_loan_days": 7, "loan_max_renewals": 1,
                                   "loan_renewal_days": 7, "loan_renewal_mode": "auto"}
    if "machines" in configuring:
        defaults["machine_policy"] = {"cert_reminder_days": 14, "reminder_lead_days": 7}
    if "events" in configuring:
        defaults["space"] = {"event_default_registration_audience": "accounts"}
        if not stored_currency:
            defaults["currency"] = "usd"
    if "membership" in configuring:
        defaults["admission"] = {"join_mode": "approval", "application_schema": APPLICATION_FORM}
    if first_setup:
        defaults["notifications"] = {"quiet_start": "22:00", "quiet_end": "08:00",
                                     "channels": QUIET_CHANNELS, "daily_digest_default": False}
    for section, values in supplied.items():
        if isinstance(values, dict):
            defaults.setdefault(section, {}).update(values)
        else:
            defaults[section] = values
    return defaults
