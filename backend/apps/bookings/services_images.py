from django.db import transaction
from rest_framework import serializers

from apps.bookings.models import BookableSpace


def _locked_space(space_id):
    return (
        BookableSpace.objects.select_for_update()
        .select_related('makerspace')
        .get(pk=space_id)
    )


def validate_space_image_key(space, object_key, storage):
    if not storage.is_owned_object_key(space, object_key):
        raise serializers.ValidationError(
            {'object_key': 'Image object key is outside this space.'}
        )
    if not storage.has_allowed_extension(object_key):
        raise serializers.ValidationError(
            {'object_key': 'Image object key has an unsupported extension.'}
        )


def _active_space(space_id):
    locked = _locked_space(space_id)
    if not locked.is_active:
        raise serializers.ValidationError(
            {'space': 'Inactive spaces cannot have images changed.'}
        )
    return locked


def _assert_active(space):
    """Cheap unlocked pre-check, so an inactive space is refused without storage I/O.

    The HEAD below is hoisted out of the row lock, which also puts it ahead of
    `_active_space`'s validation -- and an unreachable bucket then answered 503 where the
    caller should have got a 400 about the space. This is advisory only; `_active_space`
    remains the authoritative check under the lock.
    """
    if not space.is_active:
        raise serializers.ValidationError(
            {'space': 'Inactive spaces cannot have images changed.'}
        )


@transaction.atomic
def cleanup_unattached_space_image(space, *, object_key, storage):
    _locked_space(space.pk)
    if not BookableSpace.objects.filter(image_key=object_key).exists():
        storage.delete_object(object_key)
    staging_key = storage.staging_key(object_key)
    if staging_key != object_key:
        storage.delete_object(staging_key)


def set_space_image(
    space,
    *,
    actor,
    object_key,
    size_bytes,
    audit,
    limits,
    storage,
):
    # HEADed before the row lock: an S3 round trip under a held lock turns a slow bucket
    # into lock contention. No tenant-wide lock is needed -- a space's keys are prefixed
    # `spaces/<makerspace_id>/<space_pk>/images/`, so only this space can claim them.
    _assert_active(space)
    snapshot_key = space.image_key
    old_size = storage.object_size(snapshot_key) if snapshot_key else None
    locked = _active_space(space.pk)
    validate_space_image_key(locked, object_key, storage)
    if storage.public_image_key_in_use(locked.makerspace_id, object_key):
        raise serializers.ValidationError(
            {'object_key': 'This image is already in use.'}
        )
    old_key = locked.image_key
    # A concurrent replacement can move `image_key` between the unlocked snapshot and this
    # lock. Do NOT re-HEAD here to recover the size: that would put object-storage I/O
    # inside a held row lock, which is the thing hoisting the first HEAD was for. The size
    # is only an input to the missing-object validation below -- the quota release does its
    # own HEAD after commit -- so a stale snapshot simply skips that pre-check rather than
    # trading a rare race for lock contention on every slow bucket.
    if old_key and old_key == snapshot_key and old_size is None:
        raise serializers.ValidationError(
            {'image': 'The existing image was not found in storage.'}
        )
    limits.add_storage(locked.makerspace, size_bytes)
    locked.image_key = object_key
    locked.save(update_fields=['image_key', 'updated_at'])
    audit.record(
        actor,
        'booking.space_image_updated',
        makerspace=locked.makerspace,
        target=locked,
        meta={'replaced_image': bool(old_key)},
    )
    if old_key:
        storage.release_public_image_on_commit(locked.makerspace, old_key)
    locked.refresh_from_db()
    return locked


def remove_space_image(space, *, actor, audit, limits, storage):
    _assert_active(space)
    snapshot_key = space.image_key
    old_size = storage.object_size(snapshot_key) if snapshot_key else None
    locked = _active_space(space.pk)
    if not locked.image_key:
        raise serializers.ValidationError({'image': 'This space has no image.'})
    validate_space_image_key(locked, locked.image_key, storage)
    old_key = locked.image_key
    # Same reasoning as `set_space_image`: no re-HEAD under the lock. The size only feeds
    # the validation below, and the post-commit release HEADs the key it actually deletes.
    if old_key == snapshot_key and old_size is None:
        raise serializers.ValidationError(
            {'image': 'The existing image was not found in storage.'}
        )
    locked.image_key = None
    locked.save(update_fields=['image_key', 'updated_at'])
    audit.record(
        actor,
        'booking.space_image_removed',
        makerspace=locked.makerspace,
        target=locked,
        meta={},
    )
    storage.release_public_image_on_commit(locked.makerspace, old_key)
    locked.refresh_from_db()
    return locked
