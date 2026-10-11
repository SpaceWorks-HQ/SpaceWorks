# Mail a makerspace may not switch off, matched on **stream AND event** -- an event name
# alone is not unique across streams, so matching on `event` would silently exempt an
# unrelated message that happened to share the name.
#
# The first two are account recovery. They are platform mail (`makerspace=None`) and so
# are already outside the tenant gate below; they are named here anyway because the gate
# must not become tenant-scoped by accident, and because losing `email_verification`
# leaves a new account unable to verify and therefore unable to join at all.
# `return_reminder` is an overdue-loan duty-of-care message tied to the accountability
# flow, not a notification preference.
EMAIL_MODULE_EXEMPT = frozenset({
    ("account", "password_reset"),
    ("account", "email_verification"),
    ("hardware", "return_reminder"),
    ("backup", "archive_custody_alarm"),
    ("backup", "tenant_exit_custody_alarm"),
})


def email_module_blocks(makerspace, stream, event):
    """True when the `email` module is off for this makerspace and the mail is gateable.

    Platform mail has no makerspace and is never gated: there is no tenant whose toggle
    could apply, and gating it would take out forgot-password for everyone.
    """
    if makerspace is None:
        return False
    if (stream, event) in EMAIL_MODULE_EXEMPT:
        return False
    from apps.makerspaces.platform import module_enabled

    return not module_enabled(makerspace, "email")


NEVER_DEFERRED = frozenset({'return_reminder', 'closed_with_issue', 'series_generation_failed'})


def never_deferred(stream, event):
    from apps.integrations.notification_rules import ALWAYS_ON
    return event in NEVER_DEFERRED or event in ALWAYS_ON or (stream, event) in EMAIL_MODULE_EXEMPT

