"""Private stdin transport for both first-run setup and Change modules."""
import json
import sys

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from .list_modules import resolve_makerspace
from apps.makerspaces.module_install import ModuleInstallError
from apps.makerspaces.setup_area_application import apply_areas, SettingsCreatedDuringLock
from apps.makerspaces.setup_areas import area_status, active_areas


class Command(BaseCommand):
    help = "Apply setup areas and validated settings from stdin, retaining all module data."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", default=None)
        parser.add_argument("--actor", default=None)
        parser.add_argument("--answers-json", choices=("-",))
        parser.add_argument("--status", action="store_true")
        parser.add_argument("--deployment-edition", action="store_true")

    def handle(self, *args, **options):
        if options["deployment_edition"]:
            from django.conf import settings
            from apps.makerspaces.models import Makerspace
            from apps.makerspaces.servability import servable_queryset
            from apps.makerspaces.setup_areas import edition_for
            selected = set()
            for row in servable_queryset(Makerspace.objects.all()):
                selected.update(key for key, state in area_status(row).items() if state != "off")
            self.stdout.write(edition_for(selected, organization=settings.SPACEWORKS_EDITION == "organization"))
            return
        space = resolve_makerspace(options["makerspace"])
        if options["status"]:
            from apps.payments.models import MakerspacePaymentSettings
            currency = MakerspacePaymentSettings.for_makerspace(space).default_currency
            self.stdout.write(json.dumps({"makerspace": space.slug, "areas": area_status(space),
                                          "active": active_areas(space), "currency": currency}))
            return
        if options["answers_json"] != "-":
            raise CommandError("Pass --answers-json -; answers are read only from stdin.")
        users = get_user_model().objects.filter(is_superuser=True, is_active=True, access_status="active")
        if options["actor"]:
            users = users.filter(username=options["actor"])
        actor = users.order_by("pk").first()
        if actor is None:
            raise CommandError("An active superadmin actor is required.")
        try:
            raw = sys.stdin.read(65537)
            if len(raw) > 65536:
                raise ValueError("Answers exceed 64 KiB.")
            answers = json.loads(raw)
            while True:
                try:
                    apply_areas(actor, space, answers)
                    break
                except SettingsCreatedDuringLock:
                    # atomic() rolled back and released the makerspace lock. Retry
                    # now that the settings row exists, acquiring it first.
                    continue
        except (ValueError, DjangoValidationError, APIException, ModuleInstallError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Applied setup areas for {space.slug}; all module data retained."))
