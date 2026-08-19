"""Create approved deployment-global registrations from DEVICE_ATTESTATION_APPS.

Migration 0023 backfills registrations from EXISTING grants and challenges, which covers
an upgrade but not a fresh install: with no grants yet, nothing is created and native
login fails even though the operator configured DEVICE_ATTESTATION_APPS. Configuring an
app in deployment settings IS the deployment-level approval act, so this command turns
that configuration into the rows the auth path now requires. Idempotent.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models_devices import NativeAppRegistration


class Command(BaseCommand):
    help = "Provision approved global native app registrations from deployment config."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    def handle(self, *args, **options):
        configured = getattr(settings, "DEVICE_ATTESTATION_APPS", {}) or {}
        created = existing = 0
        for platform, apps_for_platform in configured.items():
            if not isinstance(apps_for_platform, dict):
                continue
            for verifier_config_key, entry in apps_for_platform.items():
                if not isinstance(entry, dict):
                    continue
                for environment in entry.get("environments") or []:
                    # Look up by the UNIQUE identity only. verifier_config_key is
                    # editable indirection and is NOT part of
                    # uniq_native_app_registration_scope, so including it here would
                    # report a row with a re-pointed verifier as absent and then violate
                    # the constraint on create() -- breaking the idempotency contract.
                    identity = {
                        "makerspace": None,
                        "app_id": verifier_config_key,
                        "platform": platform,
                        "environment": environment,
                    }
                    if NativeAppRegistration.objects.filter(**identity).exists():
                        existing += 1
                        continue
                    match = {**identity, "verifier_config_key": verifier_config_key}
                    created += 1
                    label = f"{platform}/{verifier_config_key}/{environment}"
                    if options["dry_run"]:
                        self.stdout.write(f"would create {label}")
                        continue
                    with transaction.atomic():
                        NativeAppRegistration.objects.create(
                            status=NativeAppRegistration.Status.APPROVED, **match
                        )
                    self.stdout.write(f"created {label}")
        self.stdout.write(
            self.style.SUCCESS(f"created={created} already_present={existing}")
        )
