"""Credential omission checks and explicitly reviewed non-credential fields."""
import re

from .types import Omitted
from .credentials_7b import PRINTER_NON_CREDENTIAL

CREDENTIAL_NAME = re.compile(
    r"password|secret|token|credential|webhook_url|digest|verifier|state|api_key",
    re.IGNORECASE,
)
REVIEWED_NON_CREDENTIAL = {
    ("makerspaces.MembershipRequest", "state"): "Durable request workflow state.",
    (
        "tenant_migration.ExternalTenantReference",
        "source_archive_digest",
    ): "Archive integrity identifier, not an authentication credential.",
    (
        "apiclients.ApiClient",
        "previous_secret_valid_until",
    ): "Expiry timestamp for the rotation grace window; the secret itself is omitted.",
}
REVIEWED_NON_CREDENTIAL.update(PRINTER_NON_CREDENTIAL)


def validate_credentials(fields=None):
    from .guards import RegistryError
    if fields is None:
        from .fields import FIELDS
        fields = FIELDS

    for (fidelity, label, field_name), disposition in fields.items():
        if not CREDENTIAL_NAME.search(field_name):
            continue
        if isinstance(disposition, Omitted) or (label, field_name) in REVIEWED_NON_CREDENTIAL:
            continue
        raise RegistryError(f"credential-like field not omitted: {fidelity} {label}.{field_name}")

