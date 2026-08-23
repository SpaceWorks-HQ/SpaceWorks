from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.backup.activation import repair_activation_state
from apps.backup.activation_integrity import inspect_activation_integrity


class Command(BaseCommand):
    help = "Detect or repair Lane E access-flag/activation-state divergence."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--actor-id",
            type=int,
            help="Active superuser accountable for an applied repair.",
        )

    def handle(self, *args, **options):
        issues = inspect_activation_integrity()
        if not issues:
            self.stdout.write(self.style.SUCCESS("Lane E activation state is consistent."))
            return

        for issue in issues:
            self.stdout.write(
                f"makerspace={issue.makerspace_id} issue={issue.kind} "
                f"flag={'on' if issue.flag_enabled else 'off'} "
                f"state={issue.activation_state or 'missing'} "
                f"rows={issue.activation_count}"
            )
        if not options["apply"]:
            raise CommandError(
                f"Detected {len(issues)} Lane E activation integrity issue(s). "
                "Re-run with --apply --actor-id <id> to repair them."
            )

        actor = get_user_model().objects.filter(
            pk=options["actor_id"], is_active=True, is_superuser=True
        ).first()
        if actor is None:
            raise CommandError("--actor-id must reference an active superuser.")

        repaired_ids = sorted({item.makerspace_id for item in issues})
        for makerspace_id in repaired_ids:
            repair_activation_state(makerspace_id, actor=actor)
        remaining = inspect_activation_integrity()
        if remaining:
            raise CommandError(
                "Lane E activation repair did not restore complete equality."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Repaired {len(repaired_ids)} Lane E activation row(s)."
            )
        )
