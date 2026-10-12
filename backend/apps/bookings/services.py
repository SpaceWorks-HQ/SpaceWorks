'''Explicit service barrel for bookable spaces and bookings.'''

from django.db import transaction

from apps.audit import services as audit
from apps.bookings import services_images, services_spaces, storage
from apps.bookings.models import BookableSpace
from apps.bookings.services_bookings import (
    approve_booking,
    cancel_booking,
    complete_booking,
    create_booking,
    mark_no_show,
    reject_booking,
)
from apps.bookings.services_rules import update_booking_rules
from apps.makerspaces import limits

__all__ = [
    'approve_booking',
    'cancel_booking',
    'complete_booking',
    'create_booking',
    'create_space',
    'deactivate_space',
    'mark_no_show',
    'reject_booking',
    'remove_space_image',
    'set_space_image',
    'update_booking_rules',
    'update_space',
    'validate_space_image_key',
]


def create_space(
    *, makerspace, actor, name, kind, description, capacity, location, is_public,
    show_public_availability=False, show_public_booker_names=False,
    approval_mode=BookableSpace.ApprovalMode.INSTANT, custom_form=None,
    requester_notifications_enabled=None, payment_amount=0, machine_type=None,
):
    return services_spaces.create_space(
        makerspace=makerspace,
        actor=actor,
        name=name,
        kind=kind,
        description=description,
        capacity=capacity,
        location=location,
        is_public=is_public,
        show_public_availability=show_public_availability,
        show_public_booker_names=show_public_booker_names,
        approval_mode=approval_mode,
        custom_form=custom_form,
        requester_notifications_enabled=requester_notifications_enabled,
        payment_amount=payment_amount,
        machine_type=machine_type,
        audit_service=audit,
    )


def update_space(space, *, actor, **changes):
    return services_spaces.update_space(
        space, actor=actor, audit_service=audit, **changes
    )


def deactivate_space(space, *, actor):
    return services_spaces.deactivate_space(
        space, actor=actor, audit_service=audit
    )


def validate_space_image_key(space, object_key):
    services_images.validate_space_image_key(space, object_key, storage)


@transaction.atomic
def set_space_image(space, *, actor, object_key, size_bytes):
    return services_images.set_space_image(
        space,
        actor=actor,
        object_key=object_key,
        size_bytes=size_bytes,
        audit=audit,
        limits=limits,
        storage=storage,
    )


@transaction.atomic
def remove_space_image(space, *, actor):
    return services_images.remove_space_image(
        space,
        actor=actor,
        audit=audit,
        limits=limits,
        storage=storage,
    )
