from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditLog
from apps.audit.verification import AuditMacStatus, classify_audit_row


class Command(BaseCommand):
    help = "Read and verify audit row MACs in ascending primary-key order."

    def add_arguments(self, parser):
        parser.add_argument("--start-id", type=int, default=None)
        parser.add_argument("--end-id", type=int, default=None)

    def handle(self, *args, **options):
        start_id = options["start_id"]
        end_id = options["end_id"]
        if start_id is not None and start_id < 1:
            raise CommandError("--start-id must be positive.")
        if end_id is not None and end_id < 1:
            raise CommandError("--end-id must be positive.")
        if start_id is not None and end_id is not None and start_id > end_id:
            raise CommandError("--start-id must not exceed --end-id.")

        queryset = AuditLog.objects.order_by("pk")
        if start_id is not None:
            queryset = queryset.filter(pk__gte=start_id)
        if end_id is not None:
            queryset = queryset.filter(pk__lte=end_id)

        tally = {status: 0 for status in AuditMacStatus}
        first_bad = {}
        cutover_cache = {}
        for row in queryset.iterator(chunk_size=2_000):
            status = classify_audit_row(row, cutover_cache=cutover_cache)
            tally[status] += 1
            if status in (
                AuditMacStatus.MISMATCH,
                AuditMacStatus.KEY_UNAVAILABLE,
                AuditMacStatus.MAC_MISSING,
            ):
                first_bad.setdefault(status, row.pk)
        summary = " ".join(f"{status.value}={count}" for status, count in tally.items())
        self.stdout.write(summary)
        if tally[AuditMacStatus.MISMATCH]:
            raise CommandError(
                f"Audit MAC mismatch: {tally[AuditMacStatus.MISMATCH]} row(s), "
                f"first at id={first_bad[AuditMacStatus.MISMATCH]}."
            )
        if tally[AuditMacStatus.MAC_MISSING]:
            raise CommandError(
                f"{tally[AuditMacStatus.MAC_MISSING]} row(s) written after their scope's "
                f"attestation cutover carry no MAC, first at "
                f"id={first_bad[AuditMacStatus.MAC_MISSING]}. Either the MAC was removed "
                f"from the database, or attestation degraded at write time -- search the "
                f"logs for audit_mac_key_unavailable to tell the two apart."
            )
        if tally[AuditMacStatus.KEY_UNAVAILABLE]:
            raise CommandError(
                f"Could not verify {tally[AuditMacStatus.KEY_UNAVAILABLE]} row(s): the "
                f"key for their scope is unavailable, first at "
                f"id={first_bad[AuditMacStatus.KEY_UNAVAILABLE]}. Do NOT run "
                f"provision_audit_mac_keys to fix this -- it mints a NEW random key and "
                f"would turn every one of those existing MACs into a mismatch. Restore "
                f"the original wrapped key row from backup, or correct "
                f"AUDIT_MAC_MASTER_KEY to the value those rows were sealed under."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Verified {tally[AuditMacStatus.ATTESTED]} attested row(s); "
                f"{tally[AuditMacStatus.UNATTESTED]} unattested (expected for history "
                f"before the cutover, or imported rows)."
            )
        )
