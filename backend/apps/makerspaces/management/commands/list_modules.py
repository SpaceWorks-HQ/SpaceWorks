from django.core.management.base import BaseCommand, CommandError

from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import module_status
from apps.makerspaces.module_profiles import PROFILES


class Command(BaseCommand):
    help = "List every module and whether it is installed for a makerspace."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", default=None, help="Makerspace slug (default: the only one).")

    def handle(self, *args, **options):
        makerspace = resolve_makerspace(options["makerspace"])
        self.stdout.write(f"Modules for {makerspace.slug}:")
        for row in module_status(makerspace):
            if row["core"]:
                mark, note = "*", " (core)"
            elif row["installed"]:
                mark, note = "+", ""
            else:
                mark, note = "-", ""
            requires = f" [requires {', '.join(row['requires'])}]" if row["requires"] else ""
            self.stdout.write(f"  {mark} {row['key']:<18} {row['description']}{note}{requires}")
        self.stdout.write("\n  * core (always on)   + installed   - available")
        self.stdout.write(
            "\nProfiles: " + ", ".join(f"{name} ({description})" for name, description in PROFILES.items())
        )


def resolve_makerspace(slug):
    """Shared by the install/uninstall commands: slug, or the only makerspace."""
    if slug:
        try:
            return Makerspace.objects.get(slug=slug)
        except Makerspace.DoesNotExist as exc:
            raise CommandError(f"No makerspace with slug {slug!r}.") from exc
    spaces = list(Makerspace.objects.order_by("id")[:2])
    if not spaces:
        raise CommandError("No makerspaces exist yet. Run setup_instance first.")
    if len(spaces) > 1:
        raise CommandError("More than one makerspace exists; pass --makerspace <slug>.")
    return spaces[0]
