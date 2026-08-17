"""Export one tenant from a short-lived process with DEK caching disabled.

Cache clearing is best-effort, not secure zeroization. The crypto boundary accepts
immutable ``bytes`` and ``WrappedDek`` is frozen, so plaintext copies cannot be wiped
in place. Running as a management command bounds their lifetime to this process.
"""

import argparse
import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.makerspaces.models import Makerspace
from apps.tenant_migration.archive_envelope import (
    MigrationArchiveError,
    build_tenant_migration_archive,
)
from apps.tenant_migration.gate_errors import SourceMigrationGateError
from apps.tenant_migration.preflight import SourcePreflightError


class Command(BaseCommand):
    help = "Build an age-encrypted source archive for one makerspace migration."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", required=True, metavar="SLUG")
        parser.add_argument("--output", required=True)
        parser.add_argument(
            "--owner-id",
            type=uuid.UUID,
            help="Stable UUID used to resume the same leased source gate.",
        )
        parser.add_argument(
            "--fencing-token",
            type=_positive_fencing_token,
            help="Current fencing token required when resuming a closed gate.",
        )

    def handle(self, *args, **options):
        try:
            makerspace = Makerspace.objects.get(slug=options["makerspace"])
        except Makerspace.DoesNotExist as exc:
            raise CommandError("Makerspace not found.") from exc
        if options.get("fencing_token") is not None and options.get("owner_id") is None:
            raise CommandError("--fencing-token requires --owner-id.")
        try:
            owner_id = options.get("owner_id") or uuid.uuid4()
            self.stdout.write(f"Gate owner: {owner_id}")
            path, manifest, digest = build_tenant_migration_archive(
                makerspace,
                options["output"],
                gate_owner_id=owner_id,
                gate_fencing_token=options.get("fencing_token"),
            )
        except (
            SourcePreflightError,
            MigrationArchiveError,
            SourceMigrationGateError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Archive: {path}"))
        self.stdout.write(f"SHA-256: {digest}")
        self.stdout.write(
            f"Fencing token: {manifest['source']['gate']['fencing_token']}"
        )


def _positive_fencing_token(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
