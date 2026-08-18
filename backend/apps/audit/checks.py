"""Startup checks for audit row-MAC attestation.

Attestation is opt-in (see keys.audit_mac_configured), so an unset key is a WARNING, not
an error: an existing deployment must keep booting and keep serving issue/return. A key
that is set but unusable IS an error, because that state silently produces unattested
rows while the operator believes attestation is on.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def check_audit_mac_configuration(app_configs, **kwargs):
    from apps.audit.keys import audit_mac_configured

    if not audit_mac_configured():
        return [
            Warning(
                "Audit row-MAC attestation is inactive: AUDIT_MAC_MASTER_KEY is unset.",
                hint=(
                    "New audit rows are stored unattested. Generate a Fernet key, set "
                    "AUDIT_MAC_MASTER_KEY, then run "
                    "`manage.py provision_audit_mac_keys --all`."
                ),
                id="audit.W001",
            )
        ]

    from cryptography.fernet import Fernet

    try:
        Fernet(str(settings.AUDIT_MAC_MASTER_KEY).encode("ascii"))
    except Exception:
        return [
            Error(
                "AUDIT_MAC_MASTER_KEY is set but is not a valid Fernet key.",
                hint="Generate one with Fernet.generate_key().decode('ascii').",
                id="audit.E001",
            )
        ]
    return []
