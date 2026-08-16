import copy

import pytest
from cryptography.fernet import Fernet
from django.db import IntegrityError, transaction

from apps.tenant_migration.deployment_keys import public_deployment_identity
from apps.tenant_migration.models import (
    MigrationReceipt,
    ReceiptConsumption,
)
from apps.tenant_migration.protocol_errors import (
    ReceiptReplayError,
    ReceiptValidationError,
)
from apps.tenant_migration.receipts import (
    consume_once,
    verify_and_persist_peer_receipt,
)
from tests.tenant_migration.protocol_helpers import (
    external_identity,
    signed_envelope,
    superadmin,
    target_pairing,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def encryption_key(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")


def test_deployment_public_identity_is_stable_and_never_exposes_private_material():
    first = public_deployment_identity()
    second = public_deployment_identity()

    assert first == second
    assert set(first) == {"algorithm", "deployment_id", "public_key", "fingerprint"}


def test_receipt_supplied_public_key_cannot_replace_the_pinned_key():
    actor = superadmin("unpinned-key")
    pairing, _source, _source_private = target_pairing(actor)
    attacker, attacker_private = external_identity("attacker-deployment")
    forged = signed_envelope(
        pairing,
        MigrationReceipt.Operation.SOURCE_CUTOVER,
        attacker,
        attacker_private,
    )
    forged["public_key"] = attacker["public_key"]

    with pytest.raises(ReceiptValidationError, match="not the pinned peer"):
        with transaction.atomic():
            verify_and_persist_peer_receipt(
                pairing,
                forged,
                MigrationReceipt.Operation.SOURCE_CUTOVER,
            )


def test_tampered_signed_payload_is_refused():
    actor = superadmin("tampered")
    pairing, source, source_private = target_pairing(actor)
    envelope = signed_envelope(
        pairing,
        MigrationReceipt.Operation.SOURCE_CUTOVER,
        source,
        source_private,
    )
    tampered = copy.deepcopy(envelope)
    tampered["payload"]["receipt_id"] = "00000000-0000-0000-0000-000000000001"

    with pytest.raises(ReceiptValidationError, match="signature is invalid"):
        with transaction.atomic():
            verify_and_persist_peer_receipt(
                pairing,
                tampered,
                MigrationReceipt.Operation.SOURCE_CUTOVER,
            )


def test_consumption_is_single_use_by_database_constraint():
    actor = superadmin("single-use")
    pairing, source, source_private = target_pairing(actor)
    envelope = signed_envelope(
        pairing,
        MigrationReceipt.Operation.SOURCE_CUTOVER,
        source,
        source_private,
    )
    with transaction.atomic():
        receipt = verify_and_persist_peer_receipt(
            pairing,
            envelope,
            MigrationReceipt.Operation.SOURCE_CUTOVER,
        )
        consume_once(receipt, ReceiptConsumption.Purpose.ACTIVATE_TARGET, actor)
        with pytest.raises(ReceiptReplayError) as caught:
            consume_once(receipt, ReceiptConsumption.Purpose.ACTIVATE_TARGET, actor)

    assert isinstance(caught.value.__cause__, IntegrityError)
    assert ReceiptConsumption.objects.filter(receipt=receipt).count() == 1
