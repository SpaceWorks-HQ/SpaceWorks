"""Validation and cross-model ownership checks for public image keys."""

from django.conf import settings
from django.db.models import Q
from rest_framework.exceptions import ValidationError


def public_image_key_in_use(
    makerspace_id, object_key, *, product_id=None, machine_id=None, event_id=None,
    profile_id=None, project_id=None, makerspace_field="",
):
    from apps.events.models import Event
    from apps.inventory.models import InventoryProduct
    from apps.machines.models import Machine
    from apps.makerspaces.models import Makerspace, MemberProfile, MemberProject

    products = InventoryProduct.objects.filter(
        makerspace_id=makerspace_id, image_key=object_key
    )
    if product_id is not None:
        products = products.exclude(pk=product_id)
    if products.exists():
        return True
    machines = Machine.objects.filter(
        makerspace_id=makerspace_id, image_key=object_key
    )
    if machine_id is not None:
        machines = machines.exclude(pk=machine_id)
    if machines.exists():
        return True
    events = Event.objects.filter(makerspace_id=makerspace_id, image_key=object_key)
    if event_id is not None:
        events = events.exclude(pk=event_id)
    if events.exists():
        return True
    profiles = MemberProfile.objects.filter(
        membership__makerspace_id=makerspace_id, avatar_key=object_key
    )
    if profile_id is not None:
        profiles = profiles.exclude(pk=profile_id)
    if profiles.exists():
        return True
    projects = MemberProject.objects.filter(
        profile__membership__makerspace_id=makerspace_id, image_key=object_key
    )
    if project_id is not None:
        projects = projects.exclude(pk=project_id)
    if projects.exists():
        return True
    makerspace_query = Makerspace.objects.filter(pk=makerspace_id)
    if makerspace_field == "logo_key":
        return makerspace_query.filter(cover_image_key=object_key).exists()
    if makerspace_field == "cover_image_key":
        return makerspace_query.filter(logo_key=object_key).exists()
    return makerspace_query.filter(
        Q(logo_key=object_key) | Q(cover_image_key=object_key)
    ).exists()


def public_url(object_key):
    if not object_key:
        return ""
    if settings.PUBLIC_IMAGE_BASE_URL:
        return f"{settings.PUBLIC_IMAGE_BASE_URL.rstrip('/')}/{object_key}"
    return (
        f"{settings.AWS_S3_PUBLIC_ENDPOINT_URL.rstrip('/')}/"
        f"{settings.PUBLIC_IMAGE_BUCKET}/{object_key}"
    )


def ext_for(content_type, filename):
    allowed_exts = settings.PUBLIC_IMAGE_ALLOWED_MIME.get(content_type)
    if not allowed_exts:
        raise ValidationError({"content_type": "Unsupported public image content type."})
    safe_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = f".{safe_name.rsplit('.', 1)[-1].lower()}" if "." in safe_name else ""
    if ext not in allowed_exts:
        raise ValidationError(
            {"filename": "Filename extension does not match the content type."}
        )
    return ext
