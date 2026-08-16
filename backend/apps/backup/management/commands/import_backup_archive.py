import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.backup.services import import_disaster_archive


class Command(BaseCommand):
    help = "Register a host-supplied age archive and create its disaster restore intent."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--encrypted-file", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-sha256")

    def handle(self, *args, **options):
        actor = User.objects.filter(username=options["username"]).first()
        if actor is None or not (
            actor.is_superuser or actor.role == User.Role.SUPERADMIN
        ):
            raise CommandError("The importing principal must be an existing superadmin.")
        encrypted = Path(options["encrypted_file"]).resolve()
        manifest_path = Path(options["manifest"]).resolve()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            restore = import_disaster_archive(
                actor,
                encrypted,
                manifest,
                expected_sha256=options.get("expected_sha256"),
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(restore.pk))
