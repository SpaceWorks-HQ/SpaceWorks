from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_errors import SourceMigrationRecoveryError
from apps.tenant_migration.models import SourceMigrationGate
from apps.tenant_migration.source_gate import recover_expired


class Command(BaseCommand):
    help = "Reopen an expired, orphaned pre-cutover source migration gate."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", required=True, metavar="SLUG")
        parser.add_argument(
            "--actor",
            required=True,
            metavar="USERNAME",
            help="Active superuser accountable for this recovery.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip slug-typed confirmation for non-interactive use.",
        )

    def handle(self, *args, **options):
        makerspace = Makerspace.objects.filter(slug=options["makerspace"]).first()
        if makerspace is None:
            raise CommandError("Makerspace not found.")
        actor = User.objects.filter(
            username=options["actor"], is_superuser=True, is_active=True
        ).first()
        if actor is None:
            raise CommandError(
                f"No active superuser named {options['actor']!r}."
            )

        gate = SourceMigrationGate.objects.filter(makerspace=makerspace).first()
        if gate is None or gate.state == SourceMigrationGate.State.OPEN:
            self.stdout.write("The source migration gate is already open.")
            return
        if gate.state == SourceMigrationGate.State.MIGRATED_OUT:
            raise CommandError(
                "A migrated-out source cannot be recovered by lease expiry; "
                "reopen it with the signed target abort receipt."
            )

        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    "This reopens tenant writes only after the expired-lease and "
                    "advisory-lock proofs succeed."
                )
            )
            if input("Type the makerspace slug to confirm: ").strip() != makerspace.slug:
                raise CommandError("Confirmation did not match; the gate stayed closed.")

        try:
            recovery = recover_expired(makerspace, actor)
        except SourceMigrationRecoveryError as exc:
            raise CommandError(str(exc)) from exc
        if recovery is None:
            self.stdout.write("The source migration gate is already open.")
            return
        audit.record(
            actor,
            "tenant_migration.source_gate_recovery_command",
            makerspace=None,
            target=None,
            meta={
                "makerspace_id": makerspace.pk,
                "makerspace_slug": makerspace.slug,
                "owner_id": str(recovery.previous_owner_id),
                "fencing_token": recovery.fencing_token,
                "outcome": "reopened",
            },
        )
        self.stdout.write(
            self.style.SUCCESS(f"Reopened source migration gate for {makerspace.slug}.")
        )
