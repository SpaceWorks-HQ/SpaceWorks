"""Audited mutation boundary for the Event cover image.

Split out of services.py to keep that module under the file-size ceiling, mirroring
apps/bookings/services_images.py. The image key is deliberately not part of
services.EVENT_FIELDS: it is owned by the dedicated image endpoints, so a generic
event update can never set or clear it.
"""

from django.db import transaction

from apps.audit import services as audit
from apps.events.models import Event
from apps.inventory import public_image_storage
from apps.makerspaces import limits


def _locked_event(event_id):
    return (
        Event.objects.select_for_update()
        .select_related("makerspace")
        .get(pk=event_id)
    )


def _free_stored(makerspace, object_key):
    # object_size returns None when the object is already gone from the bucket.
    # Freeing None would corrupt the counter, and the storage is genuinely no
    # longer held, so there is nothing to give back.
    size = public_image_storage.object_size(object_key)
    if size is not None:
        limits.free_storage(makerspace, size)


@transaction.atomic
def update_image(event, actor, object_key):
    locked = _locked_event(event.pk)
    old_key = locked.image_key
    if object_key == old_key:
        return locked
    limits.add_storage(
        locked.makerspace,
        public_image_storage.object_size(object_key) or 0,
    )
    if old_key:
        _free_stored(locked.makerspace, old_key)
        # Deleted after commit, not inline: a rollback further down would restore
        # image_key to old_key while the object it names had already been destroyed.
        transaction.on_commit(
            lambda key=old_key: public_image_storage.delete_object(key)
        )
    locked.image_key = object_key
    locked.save(update_fields=["image_key", "updated_at"])
    audit.record(
        actor,
        "event.image_updated",
        makerspace=locked.makerspace,
        target=locked,
        meta={"replaced_image": bool(old_key)},
    )
    locked.refresh_from_db()
    return locked


@transaction.atomic
def remove_image(event, actor):
    locked = _locked_event(event.pk)
    old_key = locked.image_key
    if not old_key:
        return locked
    _free_stored(locked.makerspace, old_key)
    locked.image_key = ""
    locked.save(update_fields=["image_key", "updated_at"])
    audit.record(
        actor,
        "event.image_removed",
        makerspace=locked.makerspace,
        target=locked,
        meta={},
    )
    transaction.on_commit(
        lambda key=old_key: public_image_storage.delete_object(key)
    )
    locked.refresh_from_db()
    return locked
