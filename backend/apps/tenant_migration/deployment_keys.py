import uuid

from django.db import transaction

from apps.makerspaces.secrets import decrypt_value, encrypt_value
from apps.tenant_migration.models_protocol import DeploymentSigningKey
from apps.tenant_migration.protocol_errors import PairingError
from apps.tenant_migration.receipt_crypto import (
    ALGORITHM,
    fingerprint_public_key,
    generate_key_material,
)

SINGLETON_ID = 1


@transaction.atomic
def deployment_signing_key():
    row = DeploymentSigningKey.objects.filter(pk=SINGLETON_ID).first()
    if row is None:
        try:
            material = generate_key_material()
            defaults = {
                "deployment_id": uuid.uuid4(),
                "private_key_ciphertext": encrypt_value(material["private_key"]),
                "public_key": material["public_key"],
                "fingerprint": material["fingerprint"],
            }
        except Exception as exc:
            raise PairingError("The deployment signing key could not be generated.") from exc
        row, _created = DeploymentSigningKey.objects.get_or_create(
            pk=SINGLETON_ID,
            defaults=defaults,
        )
    _validate_stored_key(row)
    return row


def public_deployment_identity():
    row = deployment_signing_key()
    return {
        "algorithm": ALGORITHM,
        "deployment_id": str(row.deployment_id),
        "public_key": row.public_key,
        "fingerprint": row.fingerprint,
    }


def private_key_material(row):
    _validate_stored_key(row)
    return decrypt_value(row.private_key_ciphertext)


def _validate_stored_key(row):
    try:
        if row.pk != SINGLETON_ID:
            raise PairingError("The deployment signing-key singleton is invalid.")
        if fingerprint_public_key(row.public_key) != row.fingerprint:
            raise PairingError(
                "The deployment signing public key fingerprint is invalid."
            )
        private_material = decrypt_value(row.private_key_ciphertext)
        from apps.tenant_migration.receipt_crypto import sign_payload, verify_signature

        probe = {
            "format_version": 1,
            "operation": "source_cutover",
            "receipt_id": "00000000-0000-0000-0000-000000000001",
            "migration_id": "00000000-0000-0000-0000-000000000002",
            "source_tenant_id": "key-validation",
            "archive_digest": "0" * 64,
            "source_deployment_id": "source",
            "target_deployment_id": "target",
            "signer_fingerprint": row.fingerprint,
        }
        verify_signature(probe, sign_payload(probe, private_material), row.public_key)
    except PairingError:
        raise
    except Exception as exc:
        raise PairingError("The deployment signing private key is unavailable.") from exc
