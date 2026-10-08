"""Deployment-global uniqueness rules for the exported device models (phase 7a).

Only ``devices.Device.key_fingerprint`` is a non-tenant-scoped unique column on an
exported model. UUID primary keys are excluded by the guard (the importer reserves a
fresh target UUID), and the enrollment/nonce models are omitted entirely, so their
constraints must NOT be declared here -- a stale extra declaration fails the guard.
"""

from .unique_values_policy import NULL, _policy

DEVICE_UNIQUE_RULES = {
    ("devices.Device", "field:key_fingerprint"): _policy(
        NULL, "Device keys are omitted; imported devices re-enroll with a fresh key."
    ),
}
