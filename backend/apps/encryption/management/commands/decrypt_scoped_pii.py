"""Fenced, authenticated rollback from scoped envelopes to legacy plaintext."""

from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record
from apps.encryption.crypto import PiiUnavailable, is_envelope
from apps.encryption.maintenance import decrypted_values, validate_legacy_values, write_legacy_values
from apps.encryption.blind_index import canonical_email
from apps.encryption.models import PiiBlindIndex, PiiGlobalWriteFence, PiiMakerspaceWriteFence
from apps.encryption.readiness import assert_ready
from apps.encryption.registry import all_fields, fields_for_label, registered_labels
from apps.encryption.write_fence import fence_operation

_FILTERS = {
    "hardware_requests.HardwareRequest": "makerspace_id",
    "events.EventRegistration": "event__makerspace_id",
    "bookings.Booking": "space__makerspace_id",
    "machines.MachineServiceRequest": "makerspace_id",
    "machines.MachineUsageEntry": "machine__makerspace_id",
    "integrations.EmailLog": "makerspace_id",
}


class Command(BaseCommand):
    help = "Restore authenticated scoped PII to validated legacy plaintext under rollback fencing."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", type=int)
        parser.add_argument("--global", dest="global_verify", action="store_true")
        parser.add_argument("--model", choices=sorted(registered_labels()))
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--resume-after-pk", type=int, default=0)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--verify-only", action="store_true")
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--confirm-makerspace", type=int)
        parser.add_argument("--fence-operation")

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be positive.")
        actor = get_user_model().objects.filter(
            pk=options["actor_id"], is_active=True, is_superuser=True
        ).first()
        if actor is None:
            raise CommandError("--actor-id must reference an active superuser.")
        if options["global_verify"]:
            if not options["verify_only"] or options["makerspace"] is not None:
                raise CommandError("--global is only valid with --verify-only and without --makerspace.")
            return self._verify_global()
        if options["makerspace"] is None:
            raise CommandError("--makerspace is required.")
        makerspace = apps.get_model("makerspaces.Makerspace").objects.filter(pk=options["makerspace"]).first()
        if makerspace is None:
            raise CommandError("The makerspace does not exist.")
        mutate = not options["dry_run"] and not options["verify_only"]
        operation = self._operation(options, mutate)
        if mutate:
            if options["confirm_makerspace"] != makerspace.pk:
                raise CommandError("--confirm-makerspace must equal --makerspace.")
            if not settings.PII_ENCRYPTION_ENABLED:
                raise CommandError("PII_ENCRYPTION_ENABLED must remain enabled for rollback.")
            self._assert_fences(makerspace.pk, operation)
            try:
                assert_ready()
            except PiiUnavailable as exc:
                raise CommandError("Scoped PII readiness preflight failed.") from exc
        labels = [options["model"]] if options["model"] else sorted(registered_labels())
        total = {"decrypted": 0, "plaintext": 0, "empty": 0}
        for label in labels:
            counts = self._process_model(label, makerspace.pk, actor, operation, options, mutate)
            for name, value in counts.items():
                total[name] += value
        self.stdout.write(" ".join(f"{name}={value}" for name, value in total.items()))

    def _operation(self, options, mutate):
        if not mutate:
            return None
        if not options["fence_operation"]:
            raise CommandError("--fence-operation is required for mutation.")
        try:
            return UUID(options["fence_operation"])
        except ValueError as exc:
            raise CommandError("--fence-operation must be a UUID.") from exc

    def _assert_fences(self, makerspace_id, operation):
        global_fence = PiiGlobalWriteFence.objects.filter(pk=1).first()
        tenant_fence = PiiMakerspaceWriteFence.objects.filter(makerspace_id=makerspace_id).first()
        wanted = ("closed", operation, "decrypt_rollback")
        if not global_fence or not tenant_fence or any(
            (row.state, row.operation_id, row.operation_kind) != wanted
            for row in (global_fence, tenant_fence)
        ):
            raise CommandError("Matching closed global and makerspace rollback fences are required.")

    def _process_model(self, label, makerspace_id, actor, operation, options, mutate):
        model, fields = apps.get_model(label), fields_for_label(label)
        filters = {_FILTERS[label]: makerspace_id}
        checkpoint, counts = options["resume_after_pk"], {"decrypted": 0, "plaintext": 0, "empty": 0}
        while True:
            ids = list(model.objects.filter(**filters, pk__gt=checkpoint).order_by("pk").values_list("pk", flat=True)[:options["batch_size"]])
            if not ids:
                break
            with transaction.atomic():
                makerspace = apps.get_model("makerspaces.Makerspace").objects.select_for_update().get(pk=makerspace_id)
                context = fence_operation(operation) if mutate else transaction.atomic()
                with context:
                    rows = list(model.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
                    for row in rows:
                        values = decrypted_values(row, fields)
                        for value in values.values():
                            counts["empty" if value is None else "decrypted"] += 1
                        raw_plain = sum(
                            row.__dict__.get(field.field_name, "") not in ("", None)
                            and not is_envelope(row.__dict__.get(field.field_name, ""))
                            for field in fields
                        )
                        counts["plaintext"] += raw_plain
                        if mutate and any(value is not None for value in values.values()):
                            validate_legacy_values(row, fields, values)
                            self._assert_event_email_unique(row, fields, values)
                            write_legacy_values(row, values)
                            PiiBlindIndex.objects.filter(
                                makerspace_id=makerspace_id, model_label=label, object_id=row.pk
                            ).delete()
                            if label == "events.EventRegistration":
                                model.objects.filter(pk=row.pk).update(
                                    email_exact_hash=None, email_hash_generation=None
                                )
                    checkpoint = rows[-1].pk
                    if mutate:
                        record(actor, "encryption.scoped_pii_decrypted", makerspace=makerspace,
                               meta={"model": label, "from_pk": ids[0], "to_pk": checkpoint, **counts})
            self.stdout.write(f"model={label} checkpoint={checkpoint}")
        if options["verify_only"]:
            self._verify_model(model, fields, filters, makerspace_id)
        return counts

    def _assert_event_email_unique(self, row, fields, values):
        if row._meta.label != "events.EventRegistration" or values.get("email") is None:
            return
        wanted = canonical_email(values["email"])
        for other in type(row).objects.select_for_update().filter(event_id=row.event_id).exclude(pk=row.pk):
            raw = other.__dict__.get("email", "")
            if is_envelope(raw):
                other_value = decrypted_values(other, fields).get("email")
            else:
                other_value = raw
            if canonical_email(other_value) == wanted:
                raise ValidationError({"email": "A registration already uses this email."})

    def _verify_model(self, model, fields, filters, makerspace_id):
        for row in model.objects.filter(**filters).iterator(chunk_size=200):
            values = {}
            for field in fields:
                raw = row.__dict__.get(field.field_name, "")
                if is_envelope(raw):
                    raise CommandError("Rollback verification found an envelope.")
                values[field.field_name] = raw
            try:
                validate_legacy_values(row, fields, values)
            except ValidationError as exc:
                raise CommandError("Rollback verification found an invalid legacy value.") from exc
            if row._meta.label == "events.EventRegistration" and (
                row.email_exact_hash is not None or row.email_hash_generation_id is not None
            ):
                raise CommandError("Rollback verification found an event hash.")
        if PiiBlindIndex.objects.filter(
            makerspace_id=makerspace_id, model_label=model._meta.label
        ).exists():
            raise CommandError("Rollback verification found blind-index rows.")

    def _verify_global(self):
        for field in all_fields():
            model = apps.get_model(field.model_label)
            if any(is_envelope(row[0]) for row in model.objects.values_list(field.field_name).iterator(chunk_size=200)):
                raise CommandError("Global rollback verification found an envelope.")
        if PiiBlindIndex.objects.exists():
            raise CommandError("Global rollback verification found blind-index rows.")
        event = apps.get_model("events.EventRegistration")
        if event.objects.filter(email_exact_hash__isnull=False).exists() or event.objects.filter(email_hash_generation__isnull=False).exists():
            raise CommandError("Global rollback verification found event hashes.")
        from apps.integrations.models import EmailLog
        if EmailLog.objects.filter(makerspace__isnull=True).exclude(
            to_email="", subject="Platform email", text_body="", html_body=""
        ).exists():
            raise CommandError("Global rollback verification found unredacted platform logs.")
        self.stdout.write("global_verify=ok")
