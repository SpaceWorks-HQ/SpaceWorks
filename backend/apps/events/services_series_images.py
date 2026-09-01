from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.events.models import EventSeries
from apps.inventory import public_image_storage
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked


@transaction.atomic
def update_image(series, actor, object_key):
    new_size = public_image_storage.object_size(object_key)
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    require_module_locked(locked.makerspace_id, "events")
    old_key = locked.image_key
    if object_key == old_key:
        return locked
    if public_image_storage.public_image_key_in_use(
        locked.makerspace_id, object_key, series_id=locked.pk
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    limits.add_storage(locked.makerspace, new_size or 0)
    if old_key:
        public_image_storage.release_public_image_on_commit(locked.makerspace, old_key)
    locked.image_key = object_key
    locked.save(update_fields=("image_key", "updated_at"))
    audit.record(
        actor, "event.series_image_updated", makerspace=locked.makerspace,
        target=locked, meta={"replaced_image": bool(old_key)},
    )
    return locked


@transaction.atomic
def remove_image(series, actor):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    require_module_locked(locked.makerspace_id, "events")
    old_key = locked.image_key
    if not old_key:
        return locked
    locked.image_key = ""
    locked.save(update_fields=("image_key", "updated_at"))
    audit.record(
        actor, "event.series_image_removed", makerspace=locked.makerspace, target=locked
    )
    public_image_storage.release_public_image_on_commit(locked.makerspace, old_key)
    return locked
