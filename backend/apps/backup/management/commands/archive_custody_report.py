from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from apps.backup.custody import RECIPIENT_FLOOR
from apps.makerspaces.models import Makerspace


class Command(BaseCommand):
    help = "Report self-governed makerspaces below the archive-recipient floor."

    def handle(self, *args, **options):
        spaces = (
            Makerspace.objects.filter(superadmin_access_enabled=False)
            .annotate(
                verified_recipient_count=Count(
                    "archive_recipients",
                    filter=Q(
                        archive_recipients__verified_at__isnull=False,
                        archive_recipients__revoked_at__isnull=True,
                        archive_recipients__compromised_at__isnull=True,
                    ),
                )
            )
            .filter(verified_recipient_count__lt=RECIPIENT_FLOOR)
            .select_related("archive_custody_state")
            .order_by("pk")
        )
        rows = list(spaces)
        if not rows:
            self.stdout.write(
                "No self-governed makerspaces are below the two-recipient floor."
            )
            return

        for makerspace in rows:
            try:
                custody_state = makerspace.archive_custody_state.state
            except ObjectDoesNotExist:
                custody_state = "missing"
            self.stdout.write(
                f"makerspace_id={makerspace.pk} slug={makerspace.slug} "
                f"verified_recipients={makerspace.verified_recipient_count} "
                f"custody_state={custody_state}"
            )
