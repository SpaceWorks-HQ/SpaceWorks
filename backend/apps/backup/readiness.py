"""Deployment-level archive-custody readiness summary."""

from .models import MakerspaceArchiveCustodyState


def archive_custody_readiness():
    below_floor = MakerspaceArchiveCustodyState.objects.exclude(
        state=MakerspaceArchiveCustodyState.State.HEALTHY
    ).count()
    return {"below_floor_makerspaces": below_floor}
