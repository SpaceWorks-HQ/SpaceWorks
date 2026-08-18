from django.core.management.base import BaseCommand, CommandError

from apps.audit.keys import provision_audit_mac_key
from apps.makerspaces.models import Makerspace


class Command(BaseCommand):
    help = (
        "Provision wrapped audit MAC keys before audited application traffic starts."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--all",
            action="store_true",
            help="Provision the global scope and every existing makerspace.",
        )
        group.add_argument(
            "--global",
            "--global-only",
            action="store_true",
            dest="global_scope",
            help="Provision only the global scope.",
        )
        group.add_argument(
            "--makerspace-id",
            action="append",
            type=int,
            dest="makerspace_ids",
            help="Provision one makerspace; repeat to provision several.",
        )

    def handle(self, *args, **options):
        scopes = []
        if options["all"] or options["global_scope"]:
            scopes.append(None)
        if options["all"]:
            scopes.extend(
                Makerspace.objects.order_by("pk").values_list("pk", flat=True)
            )
        elif options["makerspace_ids"]:
            requested = set(options["makerspace_ids"])
            existing = set(
                Makerspace.objects.filter(pk__in=requested).values_list(
                    "pk", flat=True
                )
            )
            missing = sorted(requested - existing)
            if missing:
                raise CommandError(
                    f"Unknown makerspace IDs: {', '.join(map(str, missing))}"
                )
            scopes.extend(sorted(existing))

        created_count = 0
        for makerspace_id in scopes:
            _, created = provision_audit_mac_key(makerspace_id)
            created_count += int(created)
            label = "global" if makerspace_id is None else str(makerspace_id)
            state = "created" if created else "already provisioned"
            self.stdout.write(f"scope={label} {state}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Audit MAC key provisioning complete: {created_count} created, "
                f"{len(scopes) - created_count} existing."
            )
        )
