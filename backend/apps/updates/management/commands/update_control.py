import json
import sys

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from apps.updates import services
from apps.updates.models import PlatformUpdateSettings
from apps.updates.rollback import create_update_snapshot, rollback_plan


class Command(BaseCommand):
    help = "Coordinate the privileged host updater with application update state."

    def add_arguments(self, parser):
        commands = parser.add_subparsers(dest="action", required=True)

        set_auto = commands.add_parser("set-auto")
        set_auto.add_argument("value", choices=("on", "off"))

        claim = commands.add_parser("claim")
        claim.add_argument("--current", default="")
        claim.add_argument("--available")
        claim.add_argument("--releases-stdin", action="store_true")
        claim.add_argument("--force", action="store_true")
        commands.add_parser("snapshot")
        commands.add_parser("rollback-plan")

        backup = commands.add_parser("record-backup")
        backup.add_argument("--name", required=True)

        complete = commands.add_parser("complete")
        complete.add_argument("--version", required=True)

        failed = commands.add_parser("fail")
        failed.add_argument("--message", required=True)

    def handle(self, *args, **options):
        action = options["action"]
        if action == "set-auto":
            settings = PlatformUpdateSettings.load()
            settings.automatic_updates_enabled = options["value"] == "on"
            settings.save(
                update_fields=("automatic_updates_enabled", "updated_at")
            )
            self.stdout.write("on" if settings.automatic_updates_enabled else "off")
            return
        if action == "claim":
            try:
                if options["releases_stdin"]:
                    raw = sys.stdin.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ValueError("The release response exceeds its size limit.")
                    claimed, version = services.claim_release(
                        current_version=options["current"].strip(), releases=json.loads(raw),
                        force=options["force"],
                    )
                    self.stdout.write(f"{'run' if claimed else 'skip'} {version}")
                else:
                    if not options["available"]:
                        raise ValueError("Use --available or --releases-stdin.")
                    claimed = services.claim_update(
                        current_version=options["current"].strip(),
                        available_version=options["available"].strip(), force=options["force"],
                    )
                    self.stdout.write("run" if claimed else "skip")
            except (ValueError, APIException) as exc:
                raise CommandError(str(exc)) from exc
            return
        if action in {"snapshot", "rollback-plan"}:
            try:
                if action == "snapshot":
                    self.stdout.write(str(create_update_snapshot().pk))
                else:
                    plan = rollback_plan()
                    self.stdout.write(f"{plan[0]} {plan[1]}" if plan else "none")
            except APIException as exc:
                raise CommandError(str(exc)) from exc
            return
        if action == "record-backup":
            services.record_backup(options["name"])
            self.stdout.write("recorded")
            return
        if action == "complete":
            services.complete_update(options["version"].strip())
            self.stdout.write("complete")
            return
        if action == "fail":
            services.fail_update(options["message"])
            self.stdout.write("failed")
            return
        raise CommandError("Unknown update control action.")
