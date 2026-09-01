from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.makerspaces.management.commands.list_modules import resolve_makerspace
from apps.makerspaces.module_purge import purge_module, purgeable_modules


class Command(BaseCommand):
    help = (
        "Irreversibly delete an uninstalled module's data for a makerspace. "
        "Uninstall retains data; this is the separate step that destroys it."
    )

    def add_arguments(self, parser):
        parser.add_argument("module", nargs="?", default=None)
        parser.add_argument("--makerspace", default=None, help="Makerspace slug (default: the only one).")
        parser.add_argument("--actor", default=None, help="Superuser username performing the purge.")
        parser.add_argument(
            "--yes", action="store_true",
            help="Skip the confirmation prompt. Required for non-interactive use.",
        )
        parser.add_argument("--list", action="store_true", help="List purgeable modules and exit.")

    def handle(self, *args, **options):
        if options["list"] or not options["module"]:
            for item in purgeable_modules():
                self.stdout.write(f"{item['key']:<20} {item['summary']}")
            if not options["module"]:
                self.stdout.write("\nPass a module key to purge it.")
            return

        makerspace = resolve_makerspace(options["makerspace"])
        actor = self._actor(options["actor"])

        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    f"This permanently deletes all {options['module']} data for "
                    f"{makerspace.slug}. It cannot be undone."
                )
            )
            if input("Type the makerspace slug to confirm: ").strip() != makerspace.slug:
                raise CommandError("Confirmation did not match; nothing was purged.")

        try:
            counts = purge_module(makerspace, options["module"], actor)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        if not counts:
            self.stdout.write(f"No {options['module']} data was present for {makerspace.slug}.")
            return
        summary = ", ".join(f"{name}={value}" for name, value in sorted(counts.items()))
        self.stdout.write(
            self.style.SUCCESS(f"Purged {options['module']} for {makerspace.slug}: {summary}")
        )

    def _actor(self, username):
        # The purge is superadmin-only, and the audit entry must name a real actor --
        # "the shell did it" is not an accountable record for an irreversible delete.
        if username:
            actor = User.objects.filter(username=username, is_superuser=True).first()
            if actor is None:
                raise CommandError(f"No superuser named {username!r}.")
            return actor
        actors = list(User.objects.filter(is_superuser=True, is_active=True)[:2])
        if len(actors) != 1:
            raise CommandError("Pass --actor <username>: there is not exactly one active superuser.")
        return actors[0]
