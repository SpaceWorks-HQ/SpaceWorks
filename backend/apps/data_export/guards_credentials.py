"""Credential-name screen used by ``guards.validate_credentials``.

Split out of ``guards`` (which sat at the 300-line ceiling); re-exported there.
"""

import re

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
