"""Machine-service purge graph and its raw-ledger deletion ordering."""

from apps.makerspaces.module_purge_collectors_single_model import _counts, _delete


def machine_service_delete(makerspace, cursor):
    # Payments and consumable pools belong to surviving modules. Service-derived usage
    # entries go because they copy requester PII from the request being purged.
    from apps.encryption.models import PiiBlindIndex
    from apps.machines.models import (
        MachineServiceRequest,
        MachineUsageEntry,
        PrintingCutoverRepair,
        PrintingCutoverState,
        ServiceBucket,
        ServiceQueue,
        ServiceRequestFile,
    )

    request_ids = list(
        MachineServiceRequest.objects.filter(makerspace=makerspace).values_list(
            "pk", flat=True
        )
    )
    doomed_entries = list(
        MachineUsageEntry.objects.filter(service_request_id__in=request_ids).values_list(
            "pk", flat=True
        )
    )
    deleted_labels = {
        "machines.MachineConsumableAdjustment",
        "machines.MachineUsageEntry",
        "machines.ServiceRequestConsumption",
    }
    usage_entries = 0
    if request_ids:
        # PROTECT ordering: consumption and adjustments point at both the request and
        # usage entry, so they must go before either parent.
        cursor.execute(
            "DELETE FROM machines_servicerequestconsumption "
            "WHERE service_request_id = ANY(%s)",
            [request_ids],
        )
        cursor.execute(
            "DELETE FROM machines_machineconsumableadjustment "
            "WHERE service_request_id = ANY(%s) OR usage_entry_id = ANY(%s)",
            [request_ids, doomed_entries],
        )
    if doomed_entries:
        PiiBlindIndex.objects.filter(
            makerspace=makerspace,
            model_label="machines.MachineUsageEntry",
            object_id__in=doomed_entries,
        ).delete()
        cursor.execute(
            "DELETE FROM machines_machineusageentry WHERE id = ANY(%s)",
            [doomed_entries],
        )
        usage_entries = cursor.rowcount

    files, labels = _delete(ServiceRequestFile.objects.filter(makerspace=makerspace))
    deleted_labels.update(labels)
    requests, labels = _delete(
        MachineServiceRequest.objects.filter(makerspace=makerspace)
    )
    deleted_labels.update(labels)
    for queryset in (
        ServiceBucket.objects.filter(machine__makerspace=makerspace),
        ServiceQueue.objects.filter(makerspace=makerspace),
        PrintingCutoverRepair.objects.filter(makerspace=makerspace),
        PrintingCutoverState.objects.filter(makerspace=makerspace),
    ):
        _, labels = _delete(queryset)
        deleted_labels.update(labels)
    return _counts(
        model_labels=deleted_labels,
        service_requests=requests,
        service_files=files,
        machine_usage_entries=usage_entries,
    )
