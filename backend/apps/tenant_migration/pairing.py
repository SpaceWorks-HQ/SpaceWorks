import re
import uuid

from django.db import transaction

from apps.audit import services as audit
from apps.accounts.models import User
from apps.tenant_migration.deployment_keys import public_deployment_identity
from apps.tenant_migration.models_protocol import MigrationPairing
from apps.tenant_migration.protocol_errors import PairingError
from apps.tenant_migration.receipt_crypto import (
    ALGORITHM,
    decode_public_key,
    fingerprint_public_key,
)

HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")


@transaction.atomic
def approve_pairing(
    *, actor, migration_id, source_tenant_id, archive_digest, source, target
):
    if not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) == User.Role.SUPERADMIN
    ):
        raise PairingError("Only a superuser can approve a deployment pairing.")
    migration_id = uuid.UUID(str(migration_id))
    source_tenant_id = str(source_tenant_id).strip()
    if not source_tenant_id or len(source_tenant_id) > 64:
        raise PairingError("The source tenant identity is invalid.")
    if not isinstance(archive_digest, str) or not HEX_64.fullmatch(archive_digest):
        raise PairingError("The source archive digest is invalid.")

    source = _validated_identity(source, "source")
    target = _validated_identity(target, "target")
    if source["deployment_id"] == target["deployment_id"]:
        raise PairingError("Source and target must be different deployments.")
    if source["fingerprint"] == target["fingerprint"]:
        raise PairingError("Source and target must use different signing keys.")
    local = public_deployment_identity()
    if not any(_same_identity(local, identity) for identity in (source, target)):
        raise PairingError("This deployment is not one of the proposed pairing peers.")

    values = {
        "source_tenant_id": source_tenant_id,
        "archive_digest": archive_digest,
        "source_deployment_id": source["deployment_id"],
        "source_public_key": source["public_key"],
        "source_fingerprint": source["fingerprint"],
        "target_deployment_id": target["deployment_id"],
        "target_public_key": target["public_key"],
        "target_fingerprint": target["fingerprint"],
        "approved_by": actor,
    }
    pairing, created = MigrationPairing.objects.get_or_create(
        migration_id=migration_id,
        defaults=values,
    )
    binding_values = {
        field: value for field, value in values.items() if field != "approved_by"
    }
    if not created and any(
        getattr(pairing, field) != value for field, value in binding_values.items()
    ):
        raise PairingError("This migration is already pinned to different peers.")
    if created:
        audit.record(
            actor,
            "tenant_migration.pairing_approved",
            target=pairing,
            meta={
                "migration_id": str(migration_id),
                "source_deployment_id": source["deployment_id"],
                "source_fingerprint": source["fingerprint"],
                "target_deployment_id": target["deployment_id"],
                "target_fingerprint": target["fingerprint"],
                "format_version": 1,
            },
        )
    return pairing


def _validated_identity(identity, label):
    if not isinstance(identity, dict):
        raise PairingError(f"The {label} deployment identity is invalid.")
    required = {"algorithm", "deployment_id", "public_key", "fingerprint"}
    if set(identity) != required or identity["algorithm"] != ALGORITHM:
        raise PairingError(f"The {label} deployment identity is invalid.")
    deployment_id = str(identity["deployment_id"]).strip()
    if not deployment_id or len(deployment_id) > 128:
        raise PairingError(f"The {label} deployment identity is invalid.")
    try:
        decode_public_key(identity["public_key"])
        computed = fingerprint_public_key(identity["public_key"])
    except Exception as exc:
        raise PairingError(f"The {label} public key is invalid.") from exc
    if identity["fingerprint"] != computed:
        raise PairingError(f"The {label} public key fingerprint does not match.")
    return {
        "algorithm": ALGORITHM,
        "deployment_id": deployment_id,
        "public_key": identity["public_key"],
        "fingerprint": computed,
    }


def _same_identity(left, right):
    return all(
        left[field] == right[field]
        for field in ("deployment_id", "public_key", "fingerprint")
    )
