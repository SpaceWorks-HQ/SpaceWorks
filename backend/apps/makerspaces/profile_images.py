"""Avatar and project images, on the shared public-image bucket.

One `member` image kind covers both. They live in the same bucket as product, machine,
event and makerspace imagery, so the key-collision rule applies here too: a key already
claimed by another object must never be attachable to a second one, or clearing either
blanks the other.
"""

from django.db import transaction

from apps.inventory import public_image_storage
from apps.makerspaces import limits

IMAGE_KIND = "member"


def _free_stored(makerspace, object_key):
    # `object_size` returns None once the object is gone from the bucket. Freeing None
    # would corrupt the counter, and the storage genuinely is no longer held.
    size = public_image_storage.object_size(object_key)
    if size is not None:
        limits.free_storage(makerspace, size)


def _swap(makerspace, holder, field, object_key):
    old_key = getattr(holder, field)
    if object_key == old_key:
        return holder
    if object_key:
        limits.add_storage(
            makerspace, public_image_storage.object_size(object_key) or 0
        )
    if old_key:
        _free_stored(makerspace, old_key)
        # Deleted after commit, not inline: a rollback below would restore the key while
        # the object it names had already been destroyed.
        transaction.on_commit(
            lambda key=old_key: public_image_storage.delete_object(key)
        )
    setattr(holder, field, object_key)
    holder.save(update_fields=[field, "updated_at"])
    return holder


@transaction.atomic
def set_avatar(profile, object_key):
    return _swap(profile.membership.makerspace, profile, "avatar_key", object_key)


@transaction.atomic
def set_project_image(profile, project, object_key):
    return _swap(profile.membership.makerspace, project, "image_key", object_key)


def clear_project_image(profile, project):
    """Release a project's image without deleting the row.

    Called from the project-replace path as well as the explicit clear, so a project the
    member removed does not strand its object in the bucket with nothing left to name it.
    """
    if project.image_key:
        set_project_image(profile, project, "")
