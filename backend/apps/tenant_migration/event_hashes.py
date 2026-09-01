"""Pre-insert reconstruction of EventRegistration's deployment-local hash."""

from apps.encryption.blind_index import active_generation, event_email_hash


def event_registration_hash_columns(
    plaintext_email, *, target_makerspace_id, target_event_id
):
    """Return raw database columns bound to the target event and active generation."""
    if not plaintext_email:
        return {"email_exact_hash": None, "email_hash_generation_id": None}
    generation = active_generation()
    return {
        "email_exact_hash": event_email_hash(
            plaintext_email,
            generation=generation.generation,
            makerspace_id=target_makerspace_id,
            event_id=target_event_id,
        ),
        "email_hash_generation_id": generation.generation,
    }
