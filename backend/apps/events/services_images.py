"""Audited mutation boundary for the Event cover image.

Split out of services.py to keep that module under the file-size ceiling, mirroring
apps/bookings/services_images.py. The image key is deliberately not part of
services.EVENT_FIELDS: it is owned by the dedicated image endpoints, so a generic
event update can never set or clear it.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

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


@transaction.atomic
def update_image(event, actor, object_key):
    # HEADed before the row lock: an S3 round trip under a held lock turns a slow bucket
    # into lock contention. No tenant-wide lock is taken -- every attach path pins the key
    # to its own `<kind>/<makerspace_id>/` prefix, so an `event/` key can only ever be
    # claimed by another Event, and this row lock is what serializes that.
    new_size = public_image_storage.object_size(object_key)
    locked = _locked_event(event.pk)
    old_key = locked.image_key
    if object_key == old_key:
        return locked
    if object_key and public_image_storage.public_image_key_in_use(
        locked.makerspace_id,
        object_key,
        event_id=locked.pk,
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    limits.add_storage(locked.makerspace, new_size or 0)
    if old_key:
        public_image_storage.release_public_image_on_commit(
            locked.makerspace, old_key
        )
    locked.image_key = object_key
    update_fields = ["image_key", "updated_at"]
    if locked.series_id:
        locked.series_override_fields = sorted(
            set(locked.series_override_fields or []) | {"image_key"}
        )
        update_fields.append("series_override_fields")
    locked.save(update_fields=update_fields)
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
    if not old_key and (
        locked.series_id is None or "image_key" in (locked.series_override_fields or [])
    ):
        return locked
    locked.image_key = ""
    update_fields = ["image_key", "updated_at"]
    if locked.series_id:
        locked.series_override_fields = sorted(
            set(locked.series_override_fields or []) | {"image_key"}
        )
        update_fields.append("series_override_fields")
    locked.save(update_fields=update_fields)
    audit.record(
        actor,
        "event.image_removed",
        makerspace=locked.makerspace,
        target=locked,
        meta={},
    )
    public_image_storage.release_public_image_on_commit(locked.makerspace, old_key)
    locked.refresh_from_db()
    return locked
