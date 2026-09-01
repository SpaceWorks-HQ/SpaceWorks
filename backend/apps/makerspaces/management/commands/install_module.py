from django.core.management.base import BaseCommand, CommandError

from apps.makerspaces.management.commands.list_modules import resolve_makerspace
from apps.makerspaces.module_install import ModuleInstallError, install_module


class Command(BaseCommand):
    help = "Enable a module (and anything it requires) for a makerspace."

    def add_arguments(self, parser):
        parser.add_argument("module")
        parser.add_argument("--makerspace", default=None, help="Makerspace slug (default: the only one).")

    def handle(self, *args, **options):
        makerspace = resolve_makerspace(options["makerspace"])
        try:
            added = install_module(makerspace, options["module"])
        except ModuleInstallError as exc:
            raise CommandError(str(exc)) from exc
        if not added:
            self.stdout.write(f"{options['module']} is already installed for {makerspace.slug}.")
            return
        # Dependencies are pulled in silently by the service, so name them here --
        # an operator who asked for one module should see what else was turned on.
        extra = [key for key in added if key != options["module"]]
        message = f"Installed {options['module']} for {makerspace.slug}."
        if extra:
            message += f" Also enabled required module(s): {', '.join(extra)}."
        self.stdout.write(self.style.SUCCESS(message))
