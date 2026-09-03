"""Card photos: staging-only presigns, single promotion to an unguessable final key, private reads.

Reuses the evidence bucket helpers: the same private bucket, the same staging prefix, the
same MIME and size bounds (`EVIDENCE_ALLOWED_MIME`, `EVIDENCE_MAX_BYTES`). The final key is
never client-writable: the browser only ever receives a presign for `staging/<key>`, and
`finalize_photo` copies it into place, deletes the staging object and saves the row.
"""
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.evidence import storage
from apps.makerspaces.limits_usage import add_storage, free_storage

PHOTO_CONSENT_VERSION = "2026-09"


def _final_key(makerspace_id):
    return f"member-cards/{makerspace_id}/{uuid.uuid4().hex}"


def presign_photo(card, content_type):
    if content_type not in settings.EVIDENCE_ALLOWED_MIME:
        raise ValidationError({"content_type": "Unsupported image type."})
    final_key = _final_key(card.makerspace_id)
    upload = storage.presigned_upload(final_key, content_type)
    return {"object_key": final_key, "content_type": content_type, **upload}


def _validate_key(card, object_key):
    prefix = f"member-cards/{card.makerspace_id}/"
    if not object_key.startswith(prefix) or "/" in object_key[len(prefix):]:
        # The prefix test stops one makerspace attaching another's object.
        raise ValidationError({"object_key": "Unknown upload."})


@transaction.atomic
def finalize_photo(actor, card, *, object_key, content_type, consent):
    _validate_key(card, object_key)
    if not consent:
        raise ValidationError({"consent": "A photo needs the member's consent to be stored."})
    staging = storage.staging_key(object_key)
    size = storage.object_size(staging)
    if not size:
        raise ValidationError({"object_key": "Upload not found; upload the photo first."})
    if size > settings.EVIDENCE_MAX_BYTES:
        storage.delete_object(staging)
        raise ValidationError({"object_key": "Photo exceeds the size limit."})
    storage.validate_evidence_object(staging)
    storage.copy_object(staging, object_key)
    storage.delete_object(staging)
    card = type(card).objects.select_for_update().get(pk=card.pk)
    old_key, old_size = card.photo_object_key, card.photo_size_bytes or 0
    add_storage(card.makerspace, size)
    card.photo_object_key = object_key
    card.photo_content_type = content_type
    card.photo_size_bytes = size
    card.photo_consent_at = timezone.now()
    card.photo_consent_version = PHOTO_CONSENT_VERSION
    card.save(
        update_fields=[
            "photo_object_key", "photo_content_type", "photo_size_bytes",
            "photo_consent_at", "photo_consent_version", "updated_at",
        ]
    )
    if old_key:
        transaction.on_commit(lambda: _release(card.makerspace, old_key, old_size))
    audit.record(actor, "member_card.photo_updated", makerspace=card.makerspace, target=card, meta={"card_id": card.pk})
    return card


def _release(makerspace, object_key, size):
    storage.delete_object(object_key)
    if size:
        free_storage(makerspace, size)


def delete_photo(card):
    """Delete the bytes and free the quota; the caller blanks the row."""
    if card.photo_object_key:
        _release(card.makerspace, card.photo_object_key, card.photo_size_bytes or 0)


def photo_url(card):
    if not card.photo_object_key:
        return None
    try:
        return storage.presigned_get_url(card.photo_object_key)
    except Exception:
        return None


def photo_bytes(card):
    """Server-side read for PDF rendering; never exposed as a URL."""
    if not card.photo_object_key:
        return None
    try:
        response = storage._client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=card.photo_object_key
        )
        return response["Body"].read(settings.EVIDENCE_MAX_BYTES)
    except Exception:
        return None
