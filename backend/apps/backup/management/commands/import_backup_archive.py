from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.backup.import_preflight import ImportPreflightError, validate_import_preflight
from apps.backup.services import import_disaster_archive


class Command(BaseCommand):
    help = "Register a host-supplied age archive and create its disaster restore intent."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--encrypted-file", required=True)
        parser.add_argument("--bundle", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--continuity-secrets", required=True)
        parser.add_argument("--expected-sha256")

    def handle(self, *args, **options):
        try:
            preflight = validate_import_preflight(
                encrypted_file=options["encrypted_file"],
                bundle=options["bundle"],
                manifest_file=options["manifest"],
                continuity_secrets_file=options["continuity_secrets"],
                expected_sha256=options["expected_sha256"],
            )
        except ImportPreflightError as exc:
            raise CommandError(str(exc)) from exc
        actor = User.objects.filter(username=options["username"]).first()
        if actor is None or not (
            actor.is_superuser or actor.role == User.Role.SUPERADMIN
        ):
            raise CommandError("The importing principal must be an existing superadmin.")
        try:
            restore = import_disaster_archive(
                actor,
                options["encrypted_file"],
                preflight.manifest,
                expected_sha256=preflight.archive_sha256,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(restore.pk))
