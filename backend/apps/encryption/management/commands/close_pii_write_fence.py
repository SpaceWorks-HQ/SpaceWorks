from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.encryption.models import PiiMakerspaceWriteFence
from apps.encryption.write_fence import close_global, close_makerspace


class Command(BaseCommand):
    help = "Close the persistent mapped-PII write fence for a maintenance operation."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--global", dest="global_fence", action="store_true")
        scope.add_argument("--makerspace", type=int)
        scope.add_argument("--all-makerspaces", action="store_true")
        parser.add_argument(
            "--operation-kind",
            choices=PiiMakerspaceWriteFence.OperationKind.values,
            required=True,
        )
        parser.add_argument("--actor-id", type=int, required=True)

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            pk=options["actor_id"], is_active=True, is_superuser=True
        ).first()
        if actor is None:
            raise CommandError("--actor-id must reference an active superuser.")
        if options["makerspace"] is not None:
            try:
                operation_id = close_makerspace(
                    options["makerspace"], options["operation_kind"], actor.id
                )
            except Exception as exc:
                raise CommandError("Could not close the PII write fence.") from exc
        else:
            try:
                operation_id = close_global(
                    options["operation_kind"],
                    actor.id,
                    all_makerspaces=options["all_makerspaces"],
                )
            except Exception as exc:
                raise CommandError("Could not close the PII write fence.") from exc
        self.stdout.write(str(operation_id))
