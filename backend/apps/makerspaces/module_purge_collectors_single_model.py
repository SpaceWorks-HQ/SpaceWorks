"""Purge collectors whose deletion is a single filtered queryset, in dependency order.

Split from `module_purge_collectors` because that module had already outgrown the 300-line
ceiling. The dividing line is a real one rather than mere size: everything here deletes one
model (or reads one model's storage keys) with no ordering constraint against another table,
while the collectors left behind coordinate several models whose delete order matters --
Payment before its generic subject, waiver-acceptance fields before waivers, provenance
before the rows it points at.

`_counts` is defined here and imported by that module rather than the reverse, because the
import already runs in that direction and duplicating it would let the two drift.
"""


class PurgeResult(dict):
    """Public row counts plus model labels owned by the plan's delete operations."""

    def __init__(self, pairs, model_labels):
        super().__init__((name, value) for name, value in pairs.items() if value)
        self.model_labels = frozenset(model_labels)


def _counts(*, model_labels=(), **pairs):
    return PurgeResult(pairs, model_labels)


def _delete(queryset):
    count, per_model = queryset.delete()
    return count, frozenset(per_model) | _cascade_model_labels(queryset.model)


def _cascade_model_labels(model, seen=None):
    """Labels this root delete owns, even when its scoped queryset is empty."""
    from django.db import models

    seen = set() if seen is None else seen
    if model in seen:
        return frozenset()
    seen.add(model)
    labels = {model._meta.label}
    for relation in model._meta.related_objects:
        if relation.field.remote_field.on_delete is models.CASCADE:
            labels.update(_cascade_model_labels(relation.related_model, seen))
    return frozenset(labels)


def bookings_delete(makerspace, cursor):
    from apps.bookings.models import BookableSpace, Booking

    bookings, booking_labels = _delete(
        Booking.objects.filter(space__makerspace=makerspace)
    )
    spaces, space_labels = _delete(BookableSpace.objects.filter(makerspace=makerspace))
    return _counts(
        model_labels=booking_labels | space_labels,
        bookings=bookings,
        bookable_spaces=spaces,
    )


def bookings_public_images(makerspace):
    from apps.bookings.models import BookableSpace

    return list(
        BookableSpace.objects.filter(makerspace=makerspace).values_list(
            "image_key", flat=True
        )
    )


def machine_service_private_keys(makerspace, add):
    from apps.machines.service_lifecycle import collect_private_object_keys

    collect_private_object_keys(makerspace, add)


def machine_service_private_key_sizes(makerspace):
    """Return charged bytes, released only after confirmed object deletion."""
    from apps.machines.models import ServiceRequestFile

    return {
        key: size
        for key, size in ServiceRequestFile.objects.filter(
            makerspace=makerspace,
            service_request__isnull=False,
        ).values_list("object_key", "size_bytes")
        if key
    }


def stocktake_delete(makerspace, cursor):
    from apps.operations.models import StocktakeSession

    deleted, labels = _delete(StocktakeSession.objects.filter(makerspace=makerspace))
    return _counts(model_labels=labels, stocktake_sessions=deleted)


def stock_transfers_delete(makerspace, cursor):
    from django.db.models import Q

    from apps.operations.models import StockTransfer

    deleted, labels = _delete(
        StockTransfer.objects.filter(
            Q(makerspace=makerspace)
            | Q(source_makerspace=makerspace)
            | Q(destination_makerspace=makerspace)
        )
        .distinct()
    )
    return _counts(model_labels=labels, stock_transfers=deleted)


def qr_print_batches_delete(makerspace, cursor):
    from apps.operations.models import QrPrintBatch

    deleted, labels = _delete(QrPrintBatch.objects.filter(makerspace=makerspace))
    return _counts(model_labels=labels, qr_print_batches=deleted)
