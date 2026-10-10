"""The `backup` module key: makerspace-facing backup surfaces only.

Gated: Space-Manager tenant archive requests/listing/downloads, archive-recipient
enrolment and lifecycle, and the custody status read. NEVER gated: recipient
compromise (security response must not wait), every deployment-level surface
(deployment backups, restores, recovery, offsite destinations) and the scheduled run,
which keeps building the per-tenant archives of superadmin-off makerspaces regardless.

Because recipient management is the only path to and from a superadmin-off
makerspace, the module cannot be uninstalled while superadmin access is disabled, and
superadmin access cannot be disabled while the module is uninstalled.
"""

from django.core.exceptions import ValidationError as DjangoValidationError

MODULE_KEY = "backup"
BACKUP_MODULE_KEY = MODULE_KEY


def assert_uninstall_allowed(locked_makerspace, before, after):
    """Called by `module_install._apply` under the makerspace row lock."""
    if (
        MODULE_KEY in before
        and MODULE_KEY not in after
        and not locked_makerspace.superadmin_access_enabled
    ):
        raise DjangoValidationError(
            "backup cannot be uninstalled while superadmin access is disabled: archive "
            "recipients are the only custody path for this makerspace.",
            code="backup_module_required",
        )
