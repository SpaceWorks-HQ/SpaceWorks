"""Managed-platform fair-use limits; deliberately dormant on self-hosts."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.makerspaces.limits_core import RESOURCE_LABELS


def custom_domain_allowed(makerspace) -> bool:
    from apps.makerspaces import limits

    if limits.is_self_host():
        return True
    return bool((makerspace.resource_limit_overrides or {}).get("custom_domain"))


def _products(makerspace) -> int:
    from apps.inventory.models import InventoryProduct

    return InventoryProduct.objects.filter(
        makerspace=makerspace, is_archived=False
    ).count()


def _assets(makerspace) -> int:
    from apps.inventory.models import InventoryAsset

    return InventoryAsset.objects.filter(
        makerspace=makerspace, product__is_archived=False
    ).count()


def _machines(makerspace) -> int:
    from apps.machines.models import Machine

    return Machine.objects.filter(makerspace=makerspace, is_active=True).count()


def _events(makerspace) -> int:
    from apps.events.models import Event

    now = datetime.now(UTC)
    return Event.objects.filter(
        makerspace=makerspace,
        status=Event.Status.PUBLISHED,
        ends_at__gte=now,
    ).count()


def _staff(makerspace) -> int:
    from apps.accounts.models import User
    from apps.makerspaces.models import MakerspaceMembership

    return MakerspaceMembership.objects.filter(
        makerspace=makerspace,
        user__is_active=True,
        user__access_status=User.AccessStatus.ACTIVE,
    ).count()


def _members(makerspace) -> int:
    from apps.accounts.models import User
    from apps.makerspaces.models import MakerspaceMembership

    return MakerspaceMembership.objects.filter(
        makerspace=makerspace, status="active", user__is_active=True,
        user__access_status=User.AccessStatus.ACTIVE,
    ).count()


def _bookings(makerspace) -> int:
    from apps.bookings.models import Booking

    return Booking.objects.filter(
        space__makerspace=makerspace,
        status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
        ends_at__gt=timezone.now(),
    ).count()


def _api_clients(makerspace) -> int:
    from apps.apiclients.models import ApiClient

    return ApiClient.objects.filter(makerspace=makerspace, is_active=True).count()


def _custom_roles(makerspace) -> int:
    from apps.makerspaces.models import MakerspaceRole

    return MakerspaceRole.objects.filter(makerspace=makerspace, is_default=False).count()


def _data_exports(makerspace) -> int:
    from apps.data_export.models import DataExportJob

    return DataExportJob.objects.filter(
        makerspace=makerspace,
        status__in=(DataExportJob.Status.PENDING, DataExportJob.Status.RUNNING),
    ).count()


def _print_requests(makerspace) -> int:
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    from apps.machines.models import MachineServiceRequest

    return MachineServiceRequest.objects.filter(
        makerspace=makerspace,
        queue__machine_type__slug="3d_printer",
        created_at__gte=month_start,
        created_at__lt=next_month,
    ).count()


def _machine_service_open(makerspace) -> int:
    from apps.machines.models import MachineServiceRequest

    return MachineServiceRequest.objects.filter(
        makerspace=makerspace,
        status__in=(
            MachineServiceRequest.Status.PENDING,
            MachineServiceRequest.Status.ACCEPTED,
            MachineServiceRequest.Status.IN_PROGRESS,
        ),
    ).count()


def _machine_service_submit(makerspace) -> int:
    from apps.machines.models import MachineServiceRequest

    now = datetime.now(UTC)
    day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return MachineServiceRequest.objects.filter(
        makerspace=makerspace,
        created_at__gte=day_start,
        created_at__lt=day_start + timedelta(days=1),
    ).count()


def _storage(makerspace) -> int:
    return makerspace.storage_bytes_used


def add_storage(makerspace, size_bytes) -> None:
    """Charge managed object storage; raise when over the storage cap.

    Opens its own ``transaction.atomic()`` so the ``select_for_update`` row lock
    works at every finalize call site regardless of whether the caller already
    holds a transaction (it degrades to a savepoint when nested). On self-host or
    unlimited it is a no-op.
    """
    from apps.makerspaces import limits

    if limits.is_self_host() or not size_bytes:
        return
    limit = limits.resource_limit(makerspace, "storage")
    if limit is None:
        return
    from django.db import transaction
    from django.db.models import F

    from apps.makerspaces.models import Makerspace

    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if locked.storage_bytes_used + size_bytes > limit:
            raise serializers.ValidationError(
                {
                    "limit": "You've reached the free storage limit for this space Ã¢â‚¬â€ ask the operator to raise it or self-host."
                },
                code="limit_reached",
            )
        Makerspace.objects.filter(pk=makerspace.pk).update(
            storage_bytes_used=F("storage_bytes_used") + size_bytes
        )


def free_storage(makerspace, size_bytes) -> None:
    """Release managed object storage (never below zero)."""
    from apps.makerspaces import limits

    if limits.is_self_host() or not size_bytes:
        return
    from apps.makerspaces.models import Makerspace
    from django.db.models import F, Value
    from django.db.models.functions import Greatest

    Makerspace.objects.filter(pk=makerspace.pk).update(
        storage_bytes_used=Greatest(F("storage_bytes_used") - size_bytes, Value(0))
    )


def _emails(makerspace) -> int:
    from apps.integrations.models import DailyEmailCounter

    today = datetime.now(UTC).date()
    return (
        DailyEmailCounter.objects.filter(makerspace=makerspace, day=today)
        .values_list("count", flat=True)
        .first()
        or 0
    )


_COUNTERS: dict[str, Callable[[object], int]] = {
    "products": _products,
    "assets": _assets,
    "machines": _machines,
    "events": _events,
    "bookings": _bookings,
    "staff": _staff,
    "members": _members,
    "api_clients": _api_clients,
    "custom_roles": _custom_roles,
    "print": _print_requests,
    "machine_service_open": _machine_service_open,
    "machine_service_submit": _machine_service_submit,
    "data_exports": _data_exports,
    "storage": _storage,
    "email": _emails,
}


def check_quota(makerspace, key, *, adding=1) -> None:
    """Raise when a managed limit would be exceeded.

    The caller must wrap this check and its create operation in
    ``transaction.atomic()`` so the makerspace row lock serializes creators.
    """
    from apps.makerspaces import limits

    limit = limits.resource_limit(makerspace, key)
    if limit is None:
        return

    counter = _COUNTERS.get(key)
    if counter is None:
        raise NotImplementedError(f"No quota counter is registered for {key!r}.")

    from apps.makerspaces.models import Makerspace

    locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    current = counter(locked)
    if current + adding > limit:
        resource = RESOURCE_LABELS.get(key, key.replace("_", " "))
        message = (
            f"You've reached the free {resource} limit for this space Ã¢â‚¬â€ "
            "ask the operator to raise it or self-host."
        )
        raise serializers.ValidationError(
            {"limit": message}, code="limit_reached"
        )
