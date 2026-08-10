"""Refresh cached GitHub contribution counts for member profiles.

Run on the operator's schedule (Celery beat, or the external cron the cloud profile
uses). Deliberately a command rather than a read-path fetch: a profile page must never
wait on GitHub, and must never break because GitHub is down.
"""

from django.core.management.base import BaseCommand

from apps.makerspaces import github_contributions
from apps.makerspaces.models import MemberProfile


class Command(BaseCommand):
    help = "Refresh cached GitHub contribution counts for member profiles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Refresh every profile with a handle, not just the stale ones.",
        )

    def handle(self, *args, **options):
        if not github_contributions.is_configured():
            self.stdout.write(
                "GITHUB_API_TOKEN is not set — contribution counts are dormant."
            )
            return
        profiles = MemberProfile.objects.exclude(github_username="")
        updated = skipped = failed = 0
        for profile in profiles:
            if not options["all"] and not github_contributions.due_for_sync(profile):
                skipped += 1
                continue
            if github_contributions.refresh(profile):
                updated += 1
            else:
                # Already logged, and the stored count is untouched. Counted rather than
                # raised: one bad handle must not stop the rest of the run.
                failed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"updated={updated} skipped={skipped} unavailable={failed}"
            )
        )
