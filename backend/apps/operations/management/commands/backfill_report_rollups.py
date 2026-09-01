from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from apps.audit import services as audit
from apps.makerspaces.models import Makerspace
from apps.operations.report_rollups import finalize_evidence_rollups


class Command(BaseCommand):
    help = "Backfill append-only report rollups in resumable tenant/day partitions."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", type=int)
        parser.add_argument("--start")
        parser.add_argument("--through")

    def handle(self, *args, **options):
        start = _datetime(options.get("start"), "start")
        through = _datetime(options.get("through"), "through")
        queryset = Makerspace.objects.order_by("id")
        if options.get("makerspace"):
            queryset = queryset.filter(pk=options["makerspace"])
        for makerspace in queryset.iterator(chunk_size=50):
            changed = finalize_evidence_rollups(
                makerspace, start_at=start, through=through, actor=None
            )
            audit.record(None, "report.rollup_backfill_completed", makerspace=makerspace, meta={
                "source_module": "evidence_uploads", "report_key": "evidence-compliance",
                "start": start.isoformat() if start else None,
                "through": through.isoformat() if through else None,
                "row_count": changed,
            })
            self.stdout.write(f"{makerspace.id}: appended {changed} rollup revisions")


def _datetime(value, label):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise CommandError(f"--{label} must be an ISO-8601 timestamp.")
    return parsed
