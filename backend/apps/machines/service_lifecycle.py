"""Purge hooks for private machine-service request data."""


def collect_private_object_keys(makerspace, add):
    from apps.machines.models import ServiceRequestFile

    for key in ServiceRequestFile.objects.filter(makerspace=makerspace).values_list("object_key", flat=True):
        add(key)


def delete_for_makerspace(makerspace, cursor):
    """Clear N1 rows in dependency order inside the authorized purge context."""
    from apps.payments.models import Payment, ProcessedStripeEvent

    from apps.machines.models import (
        MachineServiceRequest,
        MachineConsumablePool,
        PrintingCutoverRepair,
        PrintingCutoverState,
        ServiceQueue,
        ServiceBucket,
        ServiceRequestFile,
    )
    from apps.makerspaces import limits

    charged_bytes = sum(
        ServiceRequestFile.objects.filter(
            makerspace=makerspace,
            service_request__isnull=False,
        ).values_list("size_bytes", flat=True)
    )
    limits.free_storage(makerspace, charged_bytes)

    # The ledger has both ORM and DB append-only guards; raw SQL is intentional
    # here because lifecycle.purge has enabled its transaction-scoped bypass.
    cursor.execute(
        "DELETE FROM machines_servicerequestconsumption "
        "WHERE service_request_id IN ("
        "SELECT request.id FROM machines_machineservicerequest request "
        "WHERE request.makerspace_id = %s)",
        [makerspace.id],
    )
    cursor.execute("DELETE FROM machines_machineconsumableadjustment WHERE makerspace_id = %s", [makerspace.id])
    cursor.execute("DELETE FROM machines_machineusageentry WHERE machine_id IN (SELECT id FROM machines_machine WHERE makerspace_id = %s)", [makerspace.id])
    ServiceRequestFile.objects.filter(makerspace=makerspace).delete()
    # Manual settlements cascade with their payments (triggers are suspended for
    # this transaction), so the cash book needs no separate pass.
    Payment.objects.filter(makerspace=makerspace).delete()
    ProcessedStripeEvent.objects.filter(makerspace=makerspace).delete()
    MachineServiceRequest.objects.filter(makerspace=makerspace).delete()
    ServiceBucket.objects.filter(machine__makerspace=makerspace).delete()
    MachineConsumablePool.objects.filter(makerspace=makerspace).delete()
    ServiceQueue.objects.filter(makerspace=makerspace).delete()
    PrintingCutoverRepair.objects.filter(makerspace=makerspace).delete()
    PrintingCutoverState.objects.filter(makerspace=makerspace).delete()
