"""Encrypt fixed scoped PII and synchronize H3 search artifacts atomically."""

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.encryption.crypto import PiiUnavailable, is_envelope
from apps.encryption.registry import all_fields, fields_for_label, makerspace_id_for, registered_labels


FILTERS = {
    "hardware_requests.HardwareRequest": {"makerspace_id": None},
    "events.EventRegistration": {"event__makerspace_id": None},
    "bookings.Booking": {"space__makerspace_id": None},
    "machines.MachineServiceRequest": {"makerspace_id": None},
    "machines.MachineUsageEntry": {"machine__makerspace_id": None},
    "integrations.EmailLog": {"makerspace_id": None},
}


class Command(BaseCommand):
    help = "Backfill authenticated scoped PII and its generation-bound indexes."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", type=int, required=True)
        parser.add_argument("--model", choices=sorted(registered_labels()), required=True)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--resume-after-pk", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--verify-only", action="store_true")

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be positive")
        mutate = not options["dry_run"] and not options["verify_only"]
        if mutate and not settings.PII_ENCRYPTION_ENABLED:
            raise CommandError("PII_ENCRYPTION_ENABLED must be enabled before backfill.")
        label, makerspace_id = options["model"], options["makerspace"]
        model = apps.get_model(label)
        filters = FILTERS[label]
        filters = filters.copy()
        for key in filters:
            filters[key] = makerspace_id
        counts = {key: 0 for key in ("plaintext", "encrypted", "empty", "corrupt", "missing_key")}
        checkpoint = options["resume_after_pk"]
        while True:
            ids = list(model.objects.filter(**filters, pk__gt=checkpoint).order_by("pk").values_list("pk", flat=True)[:options["batch_size"]])
            if not ids:
                break
            with transaction.atomic():
                rows = list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
                for row in rows:
                    for field in fields_for_label(label):
                        raw = row.__dict__.get(field.field_name, "")
                        if raw in ("", None):
                            counts["empty"] += 1
                            continue
                        if is_envelope(raw):
                            try:
                                # Attribute access authenticates and never falls back to plaintext.
                                getattr(row, field.field_name)
                            except PiiUnavailable as exc:
                                counts["missing_key" if exc.__class__.__name__ == "PiiKeyUnavailable" else "corrupt"] += 1
                            else:
                                counts["encrypted"] += 1
                            continue
                        counts["plaintext"] += 1
                    if mutate:
                        # save() uses the row PK + registry resolver and only encrypts source fields.
                        row.save()
                checkpoint = rows[-1].pk
            self.stdout.write(f"checkpoint={checkpoint} plaintext={counts['plaintext']} encrypted={counts['encrypted']} empty={counts['empty']}")
        self.stdout.write(" ".join(f"{key}={value}" for key, value in counts.items()))
        if counts["corrupt"] or (not settings.PII_ENCRYPTION_DUAL_READ and counts["plaintext"]):
            raise CommandError("Scoped PII verification failed.")
