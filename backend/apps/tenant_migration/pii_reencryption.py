"""Rebind carried mapped-PII envelopes without changing their key version."""

from collections.abc import Mapping

from apps.encryption.crypto import decrypt_with_key_loader, encrypt, parse_envelope


def reencrypt_mapped_value(
    envelope,
    *,
    source_aad: Mapping[str, object],
    target_makerspace_id,
    target_table,
    target_pk,
    target_field,
    deks: Mapping[int, bytes],
):
    """Authenticate source ciphertext and bind it to final target identifiers.

    The envelope's declared version selects the supplied DEK and is preserved. Any
    malformed envelope, unavailable version, or authentication failure propagates and
    must abort the caller's all-or-nothing import transaction.
    """
    rebound, _plaintext = reencrypt_mapped_value_with_plaintext(
        envelope,
        source_aad=source_aad,
        target_makerspace_id=target_makerspace_id,
        target_table=target_table,
        target_pk=target_pk,
        target_field=target_field,
        deks=deks,
    )
    return rebound


def reencrypt_mapped_value_with_plaintext(
    envelope,
    *,
    source_aad: Mapping[str, object],
    target_makerspace_id,
    target_table,
    target_pk,
    target_field,
    deks: Mapping[int, bytes],
):
    """Return the rebound envelope and its bounded plaintext for derived indexes."""
    if envelope in (None, ""):
        return envelope, envelope
    version, _nonce, _ciphertext = parse_envelope(envelope)
    plaintext = decrypt_with_key_loader(
        envelope,
        makerspace_id=source_aad["makerspace_id"],
        table=source_aad["table"],
        pk=source_aad["pk"],
        field=source_aad["field"],
        load_dek=lambda declared_version: deks[declared_version],
    )
    rebound = encrypt(
        plaintext,
        deks[version],
        key_version=version,
        makerspace_id=target_makerspace_id,
        table=target_table,
        pk=target_pk,
        field=target_field,
    )
    return rebound, plaintext
