"""Name the separable apps this deployment is not using.

Module install and app tombstoning are two different axes and both are needed to run a
lean instance: uninstalling a module hides a tenant's surfaces but the deployment still
ships the code, the routes and the admin screens. `TOMBSTONED_APPS` removes those, and it
is a **deployment** decision -- process-global, identical for every tenant.

The gap this closes is discovery. An operator who installed the `lending` profile has no
way to know that `events`, `bookings`, `maintenance`, `procurement`, `presence`,
`payments` and `updates` are now dead weight, because nothing in the module list mentions
app labels. This reads what is actually installed across every makerspace and prints the
line to paste into `.env`.

Conservative by construction: an app is suggested only when **no** makerspace has any of
its modules installed. One tenant still using a module keeps the app off the list, which
is the right answer -- a tombstone would break them.
"""

from django.core.management.base import BaseCommand

from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import MODULES
from apps.separability.tombstones import SEPARABLE_APPS, tombstoned_app_labels

# Separable apps that own no module key at all, so "is any module of theirs installed?"
# cannot answer for them. Each needs its own question.
_KEYLESS_APPS = {
    "warranty": "warranty tracking (gated by core staff_admin, so it has no key of its own)",
    "presence": "geofenced check-in",
    "payments": "online payments (Stripe)",
    "updates": "the in-app software update control surface",
}


class Command(BaseCommand):
    help = "Suggest TOMBSTONED_APPS entries for modules no makerspace has installed."

    def handle(self, *args, **options):
        installed = set()
        for row in Makerspace.objects.all():
            modules = row.enabled_modules
            if isinstance(modules, list):
                installed |= {key for key in modules if isinstance(key, str)}

        apps_in_use = {
            definition.app_label
            for definition in MODULES
            if definition.key in installed
        }
        already = tombstoned_app_labels()

        unused = sorted(
            app
            for app in SEPARABLE_APPS
            if app not in apps_in_use and app not in already and app not in _KEYLESS_APPS
        )
        keyless = sorted(
            app for app in _KEYLESS_APPS if app in SEPARABLE_APPS and app not in already
        )

        if already:
            self.stdout.write(f"Already tombstoned: {', '.join(sorted(already))}\n")

        if unused:
            self.stdout.write("No makerspace has any module from these apps installed:\n")
            for app in unused:
                self.stdout.write(f"  {app}")
        else:
            self.stdout.write("Every separable app with a module key is in use.\n")

        if keyless:
            self.stdout.write(
                "\nThese own no module key, so decide by hand whether you use them:\n"
            )
            for app in keyless:
                self.stdout.write(f"  {app} -- {_KEYLESS_APPS[app]}")

        if unused:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nTo remove their surfaces, add to .env and restart:\n"
                    f"TOMBSTONED_APPS={','.join(sorted(set(unused) | already))}"
                )
            )
        self.stdout.write(
            "\nTombstoning removes surfaces only. Rows, migrations, purge plans and PII\n"
            "mappings are all retained, and deleting the label reverses it."
        )
