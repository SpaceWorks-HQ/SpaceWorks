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

from apps.makerspaces.module_purge_collectors_single_model import (
    _counts,
    bookings_delete,
    bookings_public_images,
    machine_service_private_key_sizes,
    machine_service_private_keys,
    qr_print_batches_delete,
    stock_transfers_delete,
    stocktake_delete,
)


def events_delete(makerspace, cursor):
    from apps.events.models import Event, EventCollaborator, EventRegistration

    collaborations = EventCollaborator.objects.filter(makerspace=makerspace).delete()[0]
    provenance_cleared = EventRegistration.objects.filter(
        registered_via_makerspace=makerspace,
    ).exclude(event__makerspace=makerspace).update(registered_via_makerspace=None)
    registrations = EventRegistration.objects.filter(event__makerspace=makerspace).delete()[0]
    events = Event.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(
        event_collaborations=collaborations,
        event_registration_provenance_cleared=provenance_cleared,
        event_registrations=registrations,
        events=events,
    )


def events_public_images(makerspace):
    from apps.events.models import Event

    return list(
        Event.objects.filter(makerspace=makerspace).values_list("image_key", flat=True)
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


def maintenance_private_key_sizes(makerspace):
    """Charged bytes per document key, for release after a confirmed object delete.

    `services_documents.upload_log_document` charges `limits.add_storage`, so purging the
    module must give those bytes back -- but only for objects the bucket confirms are
    gone. Freeing them alongside the row deletion looked safe because the size comes from
    a column rather than an S3 HEAD, and it is not: the rows commit, the best-effort
    object delete can then fail, and the makerspace ends up holding storage it is no
    longer charged for.
    """
    from apps.maintenance.models import MaintenanceLogDocument

    return {
        key: size
        for key, size in MaintenanceLogDocument.objects.filter(
            log__machine__makerspace=makerspace
        ).values_list("object_key", "size_bytes")
        if key
    }


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


def membership_public_image_keys(makerspace):
    """Avatars and project images, collected BEFORE the rows that name them go.

    Without this the objects outlive every row that could name them: nothing else in the
    system knows a `member/<id>/...` key exists once the profile is deleted, so they
    would sit in the bucket forever and keep counting against the space's storage.
    """
    from apps.makerspaces.models import MemberProfile, MemberProject

    keys = list(
        MemberProfile.objects.filter(membership__makerspace=makerspace).values_list(
            "avatar_key", flat=True
        )
    )
    keys += list(
        MemberProject.objects.filter(
            profile__membership__makerspace=makerspace
        ).values_list("image_key", flat=True)
    )
    return [key for key in dict.fromkeys(keys) if key]


def membership_delete(makerspace, cursor):
    from apps.events.models import EventRegistration
    from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver, MembershipRequest
    from apps.makerspaces.models import MemberProfile

    # `MakerspaceMembership` itself is core RBAC state and is NEVER deleted here -- the
    # module gates the community feature, not the roster (plan A7). But a membership
    # and a visiting registration can carry waiver acceptance under all-or-none check
    # constraints, so each set of three fields must be cleared *together* before the
    # waivers they point at go, or a constraint fires mid-purge.
    cleared = MakerspaceMembership.objects.filter(
        makerspace=makerspace, accepted_waiver__isnull=False
    ).update(accepted_waiver=None, waiver_accepted_at=None, waiver_version_accepted=None)
    event_cleared = EventRegistration.objects.filter(
        host_waiver__makerspace=makerspace,
    ).update(
        host_waiver=None,
        host_waiver_accepted_at=None,
        host_waiver_version_accepted=None,
    )
    # Profiles go even though the membership stays: a profile is community content the
    # module owns, not the RBAC state the module deliberately leaves behind. Projects
    # cascade from the profile.
    profiles = MemberProfile.objects.filter(membership__makerspace=makerspace).delete()[0]
    requests = MembershipRequest.objects.filter(makerspace=makerspace).delete()[0]
    waivers = MakerspaceWaiver.objects.filter(makerspace=makerspace).delete()[0]
    return _counts(
        waiver_acceptances_cleared=cleared,
        event_waiver_acceptances_cleared=event_cleared,
        member_profiles=profiles,
        membership_requests=requests, waivers=waivers,
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

    # Storage quota is NOT released here. It is released after the commit, and only for
    # the object keys the bucket confirmed it deleted -- see the plan's
    # `machine_service_private_key_sizes`. Freeing it inline meant the rows committed, the
    # best-effort object delete could then fail, and the makerspace stopped being charged
    # for storage it still held.

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
