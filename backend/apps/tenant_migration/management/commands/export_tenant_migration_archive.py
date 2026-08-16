"""Export one tenant from a short-lived process with DEK caching disabled.

Cache clearing is best-effort, not secure zeroization. The crypto boundary accepts
immutable ``bytes`` and ``WrappedDek`` is frozen, so plaintext copies cannot be wiped
in place. Running as a management command bounds their lifetime to this process.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.makerspaces.models import Makerspace
from apps.tenant_migration.archive_envelope import (
    MigrationArchiveError,
    build_tenant_migration_archive,
)
from apps.tenant_migration.preflight import SourcePreflightError


class Command(BaseCommand):
    help = "Build an age-encrypted source archive for one makerspace migration."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", required=True, metavar="SLUG")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            makerspace = Makerspace.objects.get(slug=options["makerspace"])
        except Makerspace.DoesNotExist as exc:
            raise CommandError("Makerspace not found.") from exc
        try:
            path, _manifest, digest = build_tenant_migration_archive(
                makerspace, options["output"]
            )
        except (SourcePreflightError, MigrationArchiveError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Archive: {path}"))
        self.stdout.write(f"SHA-256: {digest}")
