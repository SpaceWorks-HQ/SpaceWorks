"""Audit rows for `/control/` edits to platform-wide integration settings.

The staff-console API for these settings has always written `apps.audit.services.record`,
but the `/control/` forms for the same rows wrote only Django's own `LogEntry` -- which is
neither append-only nor attested, and which the audit log, its exports and the live stream
never see. A superadmin changing the SMS provider, the push credentials or a login-method
switch therefore left no entry in the trail every other credential change lands in.

The metadata names the changed FIELDS only. Several of them are write-only secret inputs
(`auth_token_raw`, `fcm_service_account_raw`, ...) and their values must never reach an
append-only row. None of the admins using this permits deletion, so only saves are hooked.
"""

from apps.audit import services as audit


class AuditedControlChangeMixin:
    """Put before the ModelAdmin base and set `audit_action` on the admin class."""

    audit_action = ""

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit.record(
            request.user,
            self.audit_action,
            target=obj,
            meta={
                "via": "control",
                "created": not change,
                "changed_fields": sorted(getattr(form, "changed_data", ()) or ()),
            },
        )
