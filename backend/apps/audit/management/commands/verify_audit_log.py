from django.core.management.base import BaseCommand, CommandError

from apps.audit.integrity import verify_audit_integrity
from apps.audit.models import AuditBatch, AuditLog


class Command(BaseCommand):
    help = "Verify row MACs, batch roots/signatures/chains, and independent anchors."

    def handle(self, *args, **options):
        failure = verify_audit_integrity()
        if failure is not None:
            coordinates = []
            if failure.makerspace_id is not None:
                coordinates.append(f"makerspace_id={failure.makerspace_id}")
            if failure.batch_seq is not None:
                coordinates.append(f"batch_seq={failure.batch_seq}")
            if failure.audit_log_id is not None:
                coordinates.append(f"audit_log_id={failure.audit_log_id}")
            location = f" ({', '.join(coordinates)})" if coordinates else ""
            raise CommandError(
                f"First audit verification failure: {failure.failure_class.value}"
                f"{location}: {failure.detail}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Verified {AuditLog.objects.count()} audit row(s) and "
                f"{AuditBatch.objects.count()} externally anchored batch(es)."
            )
        )
