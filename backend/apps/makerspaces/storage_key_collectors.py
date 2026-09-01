"""Canonical tenant object-key closure shared by migration and purge."""


def collect_private_object_keys(makerspace, *, include_coordination=True):
    from apps.evidence.models import EvidencePhoto
    from apps.events.models import EventAttendanceCertificate
    from apps.maintenance.models import MaintenanceLogDocument
    from apps.machines.models import MachineDocument
    from apps.machines.service_lifecycle import collect_private_object_keys as collect_service
    from apps.procurement.models import ToBuyReceipt
    from apps.warranty.models import WarrantyDocument

    keys, seen = [], set()

    def add(key):
        if key and key not in seen:
            seen.add(key)
            keys.append(str(key))

    for model, lookup in (
        (EvidencePhoto, {"makerspace": makerspace}),
        (EventAttendanceCertificate, {"registration__event__makerspace": makerspace}),
        (WarrantyDocument, {"warranty__makerspace": makerspace}),
        (ToBuyReceipt, {"to_buy_item__makerspace": makerspace}),
        (MaintenanceLogDocument, {"log__machine__makerspace": makerspace}),
        (MachineDocument, {"machine__makerspace": makerspace}),
    ):
        for key in model.objects.filter(**lookup).values_list("object_key", flat=True):
            add(key)
    collect_service(makerspace, add)
    if include_coordination:
        _collect_private_coordination_keys(makerspace, add)
    return keys


def collect_public_image_keys(makerspace, *, include_coordination=True):
    from apps.bookings.models import BookableSpace
    from apps.events.models import Event
    from apps.inventory.models import InventoryProduct
    from apps.machines.models import Machine
    from apps.makerspaces.models import MemberProfile, MemberProject

    keys = [makerspace.logo_key, makerspace.cover_image_key]
    for model in (BookableSpace, Event, InventoryProduct, Machine):
        keys.extend(
            model.objects.filter(makerspace=makerspace).values_list("image_key", flat=True)
        )
    keys.extend(
        MemberProfile.objects.filter(membership__makerspace=makerspace).values_list(
            "avatar_key", flat=True
        )
    )
    keys.extend(
        MemberProject.objects.filter(
            profile__membership__makerspace=makerspace
        ).values_list("image_key", flat=True)
    )
    if include_coordination:
        keys.extend(_public_coordination_keys(makerspace))
    return [str(key) for key in dict.fromkeys(keys) if key]


def _collect_private_coordination_keys(makerspace, add):
    from apps.admin_api.models import BulkImportJob
    from apps.backup.models import RestoreRollbackObject
    from apps.data_export.models import DataExportJob
    from apps.tenant_migration.models import TenantImportObject

    for name in BulkImportJob.objects.filter(makerspace=makerspace).values_list(
        "upload", flat=True
    ):
        add(name)
    for name in DataExportJob.objects.filter(makerspace=makerspace).values_list(
        "object_key", flat=True
    ):
        add(name)
    for key in RestoreRollbackObject.objects.filter(
        makerspace=makerspace,
        bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
    ).exclude(copy_key="").values_list("copy_key", flat=True):
        add(key)
    objects = TenantImportObject.objects.filter(job__target_makerspace=makerspace)
    for staging_key in objects.exclude(staging_key="").values_list(
        "staging_key", flat=True
    ):
        add(staging_key)
    for target_key in objects.filter(
        bucket_kind=TenantImportObject.BucketKind.PRIVATE
    ).exclude(target_key="").values_list("target_key", flat=True):
        add(target_key)


def _public_coordination_keys(makerspace):
    from apps.backup.models import RestoreRollbackObject
    from apps.tenant_migration.models import TenantImportObject

    keys = list(
        RestoreRollbackObject.objects.filter(
            makerspace=makerspace,
            bucket_kind=RestoreRollbackObject.BucketKind.PUBLIC_IMAGE,
        ).exclude(copy_key="").values_list("copy_key", flat=True)
    )
    keys.extend(
        TenantImportObject.objects.filter(
            job__target_makerspace=makerspace,
            bucket_kind=TenantImportObject.BucketKind.PUBLIC_IMAGE,
        ).exclude(target_key="").values_list("target_key", flat=True)
    )
    return keys
