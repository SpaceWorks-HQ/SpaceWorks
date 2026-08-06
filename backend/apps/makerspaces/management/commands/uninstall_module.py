from django.core.management.base import BaseCommand, CommandError

from apps.makerspaces.management.commands.list_modules import resolve_makerspace
from apps.makerspaces.module_install import ModuleInstallError, uninstall_module


class Command(BaseCommand):
    help = "Disable a module for a makerspace. Its data is kept and reinstalling restores it."

    def add_arguments(self, parser):
        parser.add_argument("module")
        parser.add_argument("--makerspace", default=None, help="Makerspace slug (default: the only one).")

    def handle(self, *args, **options):
        makerspace = resolve_makerspace(options["makerspace"])
        try:
            removed = uninstall_module(makerspace, options["module"])
        except ModuleInstallError as exc:
            raise CommandError(str(exc)) from exc
        if not removed:
            self.stdout.write(f"{options['module']} is not installed for {makerspace.slug}.")
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Uninstalled {options['module']} from {makerspace.slug}. "
                "Its data is retained; reinstall to restore the surfaces."
            )
        )
