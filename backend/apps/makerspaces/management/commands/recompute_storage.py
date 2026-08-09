from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.bookings.models import BookableSpace
from apps.events.models import Event
from apps.evidence import storage as evidence_storage
from apps.evidence.models import EvidencePhoto
from apps.inventory import public_image_storage
from apps.inventory.models import InventoryProduct
from apps.machines import storage as machine_storage
from apps.machines.models import Machine, MachineDocument, ServiceRequestFile
from apps.makerspaces.models import Makerspace
from apps.procurement import storage as procurement_storage
from apps.procurement.models import ToBuyReceipt
from apps.warranty import storage as warranty_storage
from apps.warranty.models import WarrantyDocument


class StorageReadError(Exception):
    pass


class Command(BaseCommand):
    help = "Recompute per-makerspace managed object-storage usage from canonical records."

    def add_arguments(self, parser):
        parser.add_argument("makerspace", nargs="?", help="Optional makerspace slug or numeric ID.")

    def handle(self, *args, **options):
        selector = options["makerspace"]
        makerspaces = Makerspace.objects.all()
        if selector:
            lookup = Q(slug=selector)
            if selector.isdigit():
                lookup |= Q(pk=int(selector))
            makerspaces = makerspaces.filter(lookup)
            if not makerspaces.exists():
                raise CommandError(f"Makerspace {selector!r} was not found.")
        else:
            makerspaces = makerspaces.filter(archived_at__isnull=True)
        for makerspace in makerspaces.order_by("pk"):
            try:
                values = {
                    "evidence": self._sum(EvidencePhoto.objects.filter(makerspace=makerspace).values_list("object_key", "size_bytes"), evidence_storage.object_size, True),
                    "print_files": self._sum(ServiceRequestFile.objects.filter(makerspace=makerspace).values_list("object_key", "size_bytes"), machine_storage.object_size, True),
                    "public_images": self._sum(((key, None) for key in self._public_image_keys(makerspace)), public_image_storage.object_size),
                    "machine_documents": self._sum(((key, None) for key in MachineDocument.objects.filter(machine__makerspace=makerspace).values_list("object_key", flat=True)), machine_storage.object_size),
                    "warranty_documents": self._sum(((key, None) for key in WarrantyDocument.objects.filter(warranty__makerspace=makerspace).values_list("object_key", flat=True)), warranty_storage.object_size),
                    "procurement_receipts": self._sum(((key, None) for key in ToBuyReceipt.objects.filter(to_buy_item__makerspace=makerspace).values_list("object_key", flat=True)), procurement_storage.object_size),
                }
            except StorageReadError as exc:
                self.stdout.write(self.style.WARNING(f"{makerspace.slug}: usage left unchanged due to storage read error for {exc}."))
                continue
            total = sum(values.values())
            Makerspace.objects.filter(pk=makerspace.pk).update(storage_bytes_used=total)
            self.stdout.write(self.style.SUCCESS(f"{makerspace.slug}: total={total} bytes"))

    @staticmethod
    def _sum(rows, object_size, fallback=False):
        total = 0
        for key, recorded in rows:
            if not key:
                continue
            try:
                observed = object_size(key)
            except Exception as exc:
                raise StorageReadError(key) from exc
            total += observed if observed is not None else ((recorded or 0) if fallback else 0)
        return total

    @staticmethod
    def _public_image_keys(makerspace):
        keys = {makerspace.logo_key, makerspace.cover_image_key}
        keys.update(InventoryProduct.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        keys.update(Machine.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        keys.update(Event.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        # BookableSpace images are charged on upload and collected by lifecycle purge,
        # but were missing here, so the reconciler wrote a total that omitted them and
        # silently lowered a space's recorded usage. apps/bookings/storage.py is a thin
        # wrapper over public_image_storage, so these live in the same bucket.
        keys.update(BookableSpace.objects.filter(makerspace=makerspace).values_list("image_key", flat=True))
        return {key for key in keys if key}
