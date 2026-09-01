"""Bounded repair/rebuild of only registry-approved search material."""

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.encryption.blind_index import active_generation, sync_event_hash, upsert_index
from apps.encryption.models import PiiBlindIndex
from apps.encryption.registry import fields_for_label


FILTERS = {
    "hardware_requests.HardwareRequest": "makerspace_id",
    "events.EventRegistration": "event__makerspace_id",
    "machines.MachineServiceRequest": "makerspace_id",
    "machines.MachineUsageEntry": "machine__makerspace_id",
}


def _generic_discrepancies(row, field, generation):
    """Return 1 when a nonempty value lacks an active-generation index row, or an
    empty value still carries one (stale)."""
    value = getattr(row, field.field_name)
    exists = PiiBlindIndex.objects.filter(
        model_label=field.model_label, object_id=row.pk,
        field_name=field.field_name, search_generation=generation,
    ).exists()
    return 1 if bool(value) != exists else 0


def _event_discrepancies(row, field, generation):
    value = getattr(row, field.field_name)
    bound = row.email_exact_hash is not None and row.email_hash_generation_id == generation.pk
    if value:
        return 0 if bound else 1
    return 0 if (row.email_exact_hash is None and row.email_hash_generation_id is None) else 1


class Command(BaseCommand):
    help = "Rebuild generation-bound scoped PII blind indexes without printing values."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", type=int, required=True)
        parser.add_argument("--model", choices=sorted(FILTERS), required=True)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--resume-after-pk", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--verify-only", action="store_true")

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be positive")
        if not settings.PII_ENCRYPTION_ENABLED and not (options["dry_run"] or options["verify_only"]):
            raise CommandError("PII_ENCRYPTION_ENABLED must be enabled before reindexing.")
        generation = active_generation() if settings.PII_ENCRYPTION_ENABLED else None
        mutate = not (options["dry_run"] or options["verify_only"])
        verify = options["verify_only"] and generation is not None
        model = apps.get_model(options["model"])
        checkpoint, count, problems = options["resume_after_pk"], 0, 0
        filters = {FILTERS[options["model"]]: options["makerspace"]}
        while True:
            ids = list(model.objects.filter(**filters, pk__gt=checkpoint).order_by("pk").values_list("pk", flat=True)[:options["batch_size"]])
            if not ids:
                break
            with transaction.atomic():
                rows = list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
                for row in rows:
                    for field in fields_for_label(options["model"]):
                        if field.index_kind in {"bloom", "bloom_exact"}:
                            if mutate:
                                upsert_index(row, field, getattr(row, field.field_name), generation)
                            elif verify:
                                problems += _generic_discrepancies(row, field, generation)
                        elif field.index_kind == "event_exact":
                            if mutate:
                                sync_event_hash(row, getattr(row, field.field_name), generation)
                                model.objects.filter(pk=row.pk).update(email_exact_hash=row.email_exact_hash, email_hash_generation=row.email_hash_generation)
                            elif verify:
                                problems += _event_discrepancies(row, field, generation)
                    count += 1
                checkpoint = rows[-1].pk
            self.stdout.write(f"checkpoint={checkpoint} rows={count} problems={problems}")
        self.stdout.write(f"rows={count} problems={problems}")
        if verify and problems:
            raise CommandError(f"Reindex verification failed: {problems} missing or stale artifacts.")
