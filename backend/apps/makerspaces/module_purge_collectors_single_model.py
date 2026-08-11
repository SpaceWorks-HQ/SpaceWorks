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


def _counts(**pairs):
    return {name: value for name, value in pairs.items() if value}


def bookings_delete(makerspace, cursor):
    from apps.bookings.models import BookableSpace, Booking

    bookings = Booking.objects.filter(space__makerspace=makerspace).delete()[0]
    spaces = BookableSpace.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(bookings=bookings, bookable_spaces=spaces)


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

    return _counts(
        stocktake_sessions=StocktakeSession.objects.filter(
            makerspace=makerspace
        ).delete()[0]
    )


def stock_transfers_delete(makerspace, cursor):
    from django.db.models import Q

    from apps.operations.models import StockTransfer

    deleted = (
        StockTransfer.objects.filter(
            Q(makerspace=makerspace)
            | Q(source_makerspace=makerspace)
            | Q(destination_makerspace=makerspace)
        )
        .distinct()
        .delete()[0]
    )
    return _counts(stock_transfers=deleted)


def qr_print_batches_delete(makerspace, cursor):
    from apps.operations.models import QrPrintBatch

    return _counts(
        qr_print_batches=QrPrintBatch.objects.filter(
            makerspace=makerspace
        ).delete()[0]
    )
