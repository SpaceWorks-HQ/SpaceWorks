"""Periodic makerspace tasks."""

from celery import shared_task


@shared_task(name="apps.makerspaces.tasks.refresh_github_contributions_task")
def refresh_github_contributions_task():
    """Refresh the cached GitHub contribution counts on maker profiles.

    Scheduled rather than fetched on read, so a slow or rate-limited GitHub can never
    make a profile page slow and can never make it fail. Dormant when
    `GITHUB_API_TOKEN` is unset: nothing is called and every count stays None.
    """
    from apps.makerspaces import github_contributions
    from apps.makerspaces.models import MemberProfile

    if not github_contributions.is_configured():
        return {"configured": False}
    updated = unavailable = 0
    for profile in MemberProfile.objects.exclude(github_username=""):
        if not github_contributions.due_for_sync(profile):
            continue
        # `refresh` swallows every failure and keeps the last known count, so one bad
        # handle cannot stop the rest of the run.
        if github_contributions.refresh(profile):
            updated += 1
        else:
            unavailable += 1
    return {"configured": True, "updated": updated, "unavailable": unavailable}
