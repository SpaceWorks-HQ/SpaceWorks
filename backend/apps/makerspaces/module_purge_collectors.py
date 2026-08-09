"""How each module's rows are actually removed (plan A9).

One function per module, called from `module_purge_plans.PLANS` inside the purge
transaction, after the caller has opened the transaction-scoped immutability bypass.
Splitting these out of the plan registry keeps "which plans exist" readable next to
"what each one deletes", and keeps both files inside the file-size ceiling.

Two rules every collector here obeys:

* **Only what this module owns.** The makerspace survives the purge and other modules
  stay installed, so a collector must not reach into their rows -- see
  `machine_service_delete`, which is deliberately narrower than the whole-tenant
  `machines.service_lifecycle.delete_for_makerspace`.
* **Model imports are function-local.** This module is imported by the plan registry,
  which the management command imports at load time; importing app models at module
  scope would drag half the app graph into every `manage.py` invocation.
"""


def _counts(**pairs):
    return {name: value for name, value in pairs.items() if value}


def events_delete(makerspace, cursor):
    from apps.events.models import Event, EventRegistration

    registrations = EventRegistration.objects.filter(event__makerspace=makerspace).delete()[0]
    events = Event.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(event_registrations=registrations, events=events)


def bookings_delete(makerspace, cursor):
    from apps.bookings.models import BookableSpace, Booking

    bookings = Booking.objects.filter(space__makerspace=makerspace).delete()[0]
    spaces = BookableSpace.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(bookings=bookings, bookable_spaces=spaces)


def events_public_images(makerspace):
    from apps.events.models import Event

    return list(
        Event.objects.filter(makerspace=makerspace).values_list("image_key", flat=True)
    )


def bookings_public_images(makerspace):
    from apps.bookings.models import BookableSpace

    return list(
        BookableSpace.objects.filter(makerspace=makerspace).values_list("image_key", flat=True)
    )


def maintenance_delete(makerspace, cursor):
    from apps.maintenance.models import (
        MaintenanceLog,
        MaintenanceLogDocument,
        MaintenanceSchedule,
    )

    documents = MaintenanceLogDocument.objects.filter(
        log__machine__makerspace=makerspace
    ).delete()[0]
    logs = MaintenanceLog.objects.filter(machine__makerspace=makerspace).delete()[0]
    schedules = MaintenanceSchedule.objects.filter(machine__makerspace=makerspace).delete()[0]
    return _counts(documents=documents, logs=logs, schedules=schedules)


def maintenance_private_keys(makerspace, add):
    from apps.maintenance.models import MaintenanceLogDocument

    for key in MaintenanceLogDocument.objects.filter(
        log__machine__makerspace=makerspace
    ).values_list("object_key", flat=True):
        add(key)


def procurement_delete(makerspace, cursor):
    from apps.procurement.models import ToBuyItem, ToBuyReceipt

    receipts = ToBuyReceipt.objects.filter(to_buy_item__makerspace=makerspace).delete()[0]
    items = ToBuyItem.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(receipts=receipts, to_buy_items=items)


def procurement_private_keys(makerspace, add):
    from apps.procurement.models import ToBuyReceipt

    for key in ToBuyReceipt.objects.filter(
        to_buy_item__makerspace=makerspace
    ).values_list("object_key", flat=True):
        add(key)


def notifications_delete(makerspace, cursor):
    from apps.notifications.models import Notification

    return _counts(
        notifications=Notification.objects.filter(makerspace=makerspace).delete()[0]
    )


def _chat_destinations_delete(makerspace, channel):
    """Delete one chat channel's rooms and their stored credentials.

    This was not needed while a channel's credential was a column on `Makerspace` — the
    channel owned no rows at all. A destination holds an encrypted webhook URL or chat id,
    so purging `discord` after uninstalling it must destroy those secrets, not leave them
    readable in a table nothing surfaces any more. The scope link tables and the delivery
    logs' `destination` FK both fall out of this by CASCADE and SET_NULL respectively:
    history survives, the credential does not.
    """
    from apps.integrations.models_destinations import NotificationDestination

    return _counts(
        destinations=NotificationDestination.objects.filter(
            makerspace=makerspace, channel=channel
        ).delete()[0]
    )


def telegram_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "telegram")


def slack_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "slack")


def mattermost_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "mattermost")


def discord_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "discord")


def membership_delete(makerspace, cursor):
    from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver, MembershipRequest

    # `MakerspaceMembership` itself is core RBAC state and is NEVER deleted here -- the
    # module gates the community feature, not the roster (plan A7). But a membership
    # carries a waiver acceptance under an all-or-none check constraint, so the three
    # acceptance fields must be cleared *together* before the waivers they point at go,
    # or the constraint fires mid-purge.
    cleared = MakerspaceMembership.objects.filter(
        makerspace=makerspace, accepted_waiver__isnull=False
    ).update(accepted_waiver=None, waiver_accepted_at=None, waiver_version_accepted=None)
    requests = MembershipRequest.objects.filter(makerspace=makerspace).delete()[0]
    waivers = MakerspaceWaiver.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(
        waiver_acceptances_cleared=cleared, membership_requests=requests, waivers=waivers
    )


def machine_service_delete(makerspace, cursor):
    # The whole-tenant twin of this is `machines.service_lifecycle.delete_for_makerspace`,
    # which is called by `lifecycle.purge()`. It is deliberately NOT reused, and the two
    # differ in more than scope: there the whole makerspace goes, so it can delete every
    # Payment, every usage entry and every consumable pool. Here `machines` is still
    # installed, so this must delete only what `machine_service` owns:
    #   * Payments of THIS module's subject type (handled by the caller) -- deleting all
    #     of them would destroy booking and event-registration charges.
    #   * Consumable POOLS stay. They are gated by `require_module(..., "machines")`
    #     (`views_machine_consumables.py`), are created from procurement, and surviving
    #     manual usage entries PROTECT-reference them.
    #   * Usage entries derived from a service request GO. They carry the requester's
    #     name/email/phone copied off the request, so leaving them behind would defeat
    #     the purge; manual entries (`service_request IS NULL`) are machines-module
    #     history and stay.
    # Consumable ledger rows are deleted, not reversed: the material really was consumed,
    # so the pool keeps its `remaining_grams` and loses only the audit trail -- the same
    # trade every purge makes.
    from apps.machines.models import (
        MachineServiceRequest,
        PrintingCutoverRepair,
        PrintingCutoverState,
        ServiceBucket,
        ServiceQueue,
        ServiceRequestFile,
    )
    from apps.makerspaces import limits

    charged_bytes = sum(
        ServiceRequestFile.objects.filter(
            makerspace=makerspace, service_request__isnull=False
        ).values_list("size_bytes", flat=True)
    )
    limits.free_storage(makerspace, charged_bytes)

    # Append-only ledgers with both ORM and DB guards, so the deletes go through raw SQL
    # under the transaction-scoped bypass the caller opened. The id sets are resolved in
    # Python rather than as subqueries: it keeps the PROTECT ordering readable, and the
    # blind-index cleanup needs the usage-entry ids anyway.
    from apps.encryption.models import PiiBlindIndex
    from apps.machines.models import MachineUsageEntry

    request_ids = list(
        MachineServiceRequest.objects.filter(makerspace=makerspace).values_list("pk", flat=True)
    )
    doomed_entries = list(
        MachineUsageEntry.objects.filter(service_request_id__in=request_ids).values_list(
            "pk", flat=True
        )
    )
    usage_entries = 0
    if request_ids:
        # PROTECT ordering: consumption and adjustments point at both the request and
        # the usage entry, so they go before either.
        cursor.execute(
            "DELETE FROM machines_servicerequestconsumption WHERE service_request_id = ANY(%s)",
            [request_ids],
        )
        cursor.execute(
            "DELETE FROM machines_machineconsumableadjustment "
            "WHERE service_request_id = ANY(%s) OR usage_entry_id = ANY(%s)",
            [request_ids, doomed_entries],
        )
    if doomed_entries:
        # Blind-index rows are removed per-id, not per-label: the surviving manual usage
        # entries share the label and must keep theirs, or search silently loses them.
        PiiBlindIndex.objects.filter(
            makerspace=makerspace,
            model_label="machines.MachineUsageEntry",
            object_id__in=doomed_entries,
        ).delete()
        cursor.execute(
            "DELETE FROM machines_machineusageentry WHERE id = ANY(%s)", [doomed_entries]
        )
        usage_entries = cursor.rowcount
    files = ServiceRequestFile.objects.filter(makerspace=makerspace).delete()[0]
    requests = MachineServiceRequest.objects.filter(makerspace=makerspace).delete()[0]
    ServiceBucket.objects.filter(machine__makerspace=makerspace).delete()
    ServiceQueue.objects.filter(makerspace=makerspace).delete()
    PrintingCutoverRepair.objects.filter(makerspace=makerspace).delete()
    PrintingCutoverState.objects.filter(makerspace=makerspace).delete()
    return _counts(
        service_requests=requests, service_files=files, machine_usage_entries=usage_entries
    )


def machine_service_private_keys(makerspace, add):
    from apps.machines.service_lifecycle import collect_private_object_keys

    collect_private_object_keys(makerspace, add)


def stocktake_delete(makerspace, cursor):
    from apps.operations.models import StocktakeSession

    return _counts(
        stocktake_sessions=StocktakeSession.objects.filter(makerspace=makerspace).delete()[0]
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
        qr_print_batches=QrPrintBatch.objects.filter(makerspace=makerspace).delete()[0]
    )
