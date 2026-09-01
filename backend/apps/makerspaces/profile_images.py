"""Avatar and project images, on the shared public-image bucket.

One `member` image kind covers both. They live in the same bucket as product, machine,
event and makerspace imagery, so the key-collision rule applies here too: a key already
claimed by another object must never be attachable to a second one, or clearing either
blanks the other.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.inventory import public_image_storage
from apps.makerspaces import limits

IMAGE_KIND = "member"


def _swap(
    makerspace, holder, field, object_key, *, profile, profile_id=None, project_id=None,
):
    # HEADed before any lock is taken: an S3 round trip while a row lock is held turns a
    # slow bucket into lock contention.
    new_size = public_image_storage.object_size(object_key) if object_key else 0
    # `member` is the ONE image kind with two holder tables -- an avatar on the profile
    # and an image on each of its projects -- so a row lock on the holder alone cannot
    # serialize a profile's claim against its own project's. Locking the PROFILE does,
    # because every member-kind key belongs to exactly one profile. A tenant-wide lock
    # would also work and is deliberately not taken: it would serialize every image
    # upload in the space against every other, including on self-host where
    # `limits.add_storage` takes no makerspace lock at all today.
    profile = type(profile).objects.select_for_update().get(pk=profile.pk)
    # Re-read under a row lock inside the caller's transaction. The holder was fetched
    # before it, so two overlapping replacements would both see the same `old_key`:
    # each charges storage for its new object, each frees the same old one, the last
    # save wins, and the loser's object is orphaned in the bucket with the counter left
    # overcharged. This is `services_images._locked_event`'s reason, on the same shape.
    holder = type(holder).objects.select_for_update().get(pk=holder.pk)
    old_key = getattr(holder, field)
    if object_key == old_key:
        return holder
    if object_key and public_image_storage.public_image_key_in_use(
        makerspace.pk,
        object_key,
        profile_id=profile_id,
        project_id=project_id,
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    if object_key:
        limits.add_storage(makerspace, new_size or 0)
    if old_key:
        public_image_storage.release_public_image_on_commit(makerspace, old_key)
    setattr(holder, field, object_key)
    holder.save(update_fields=[field, "updated_at"])
    return holder


@transaction.atomic
def set_avatar(profile, object_key):
    membership = profile.membership
    result = _swap(
        membership.makerspace,
        profile,
        "avatar_key",
        object_key,
        profile=profile,
        profile_id=profile.pk,
    )
    _audit_image(membership, "avatar", None, object_key)
    return result


@transaction.atomic
def set_project_image(profile, project, object_key):
    membership = profile.membership
    result = _swap(
        membership.makerspace,
        project,
        "image_key",
        object_key,
        profile=profile,
        project_id=project.pk,
    )
    _audit_image(membership, "project", project.pk, object_key)
    return result


def _audit_image(membership, kind, project_id, object_key):
    """Attaching and clearing member imagery are state changes and are recorded.

    The object key is deliberately NOT logged: it is an identifier for a public object,
    and the audit log is append-only, so a key written here outlives the image and every
    row that could name it. Whether one was attached or cleared is the fact worth having.
    """
    audit.record(
        membership.user,
        "member.profile_image_cleared" if not object_key else "member.profile_image_updated",
        makerspace=membership.makerspace,
        target=membership,
        meta={"kind": kind, "project_id": project_id},
    )


def clear_project_image(profile, project):
    """Release a project's image without deleting the row.

    Called from the project-replace path as well as the explicit clear, so a project the
    member removed does not strand its object in the bucket with nothing left to name it.
    """
    if project.image_key:
        set_project_image(profile, project, "")
