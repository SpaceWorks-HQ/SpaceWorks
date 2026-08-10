"""Optional GitHub contribution counts, fetched off the request path and cached.

Three rules, all of which exist because a profile must never depend on GitHub being up:

* **Never fetched during a read.** The count is refreshed by a Celery task and by
  `refresh_github_contributions` on the operator's schedule. A rate-limited or slow
  GitHub therefore cannot make a profile page slow, and cannot make it fail.
* **A failure never clears the stored count.** The last known number keeps showing.
  `github_synced_at` is stamped even on failure, so a broken or throttled API is not
  retried on every pass — the sync backs off rather than hammering.
* **Dormant unless configured.** The contribution calendar is only available through
  GitHub's GraphQL API, which requires a token. With `GITHUB_API_TOKEN` unset nothing is
  fetched, the count stays None and the surface omits the section entirely.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
SYNC_INTERVAL = timedelta(hours=24)
REQUEST_TIMEOUT = 10

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar { totalContributions }
    }
  }
}
"""


def is_configured():
    return bool((getattr(settings, "GITHUB_API_TOKEN", "") or "").strip())


def due_for_sync(profile, now=None):
    if not profile.github_username or not is_configured():
        return False
    if profile.github_synced_at is None:
        return True
    return (now or timezone.now()) - profile.github_synced_at >= SYNC_INTERVAL


def refresh(profile):
    """Update one profile's count. Returns True when a fresh number was stored."""
    from apps.makerspaces.models import MemberProfile

    total = fetch_total(profile.github_username)
    fields = {"github_synced_at": timezone.now()}
    if total is not None:
        fields["github_contributions"] = total
    # `.update()` rather than `save()`: this runs from a task, and a full save would
    # write back whatever the member edited between the read and now.
    MemberProfile.objects.filter(pk=profile.pk).update(**fields)
    return total is not None


def fetch_total(login):
    """The contribution total, or None for any failure at all."""
    if not login or not is_configured():
        return None
    request = urllib.request.Request(
        GITHUB_GRAPHQL_URL,
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={
            "Authorization": f"Bearer {settings.GITHUB_API_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "SpaceWorks",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            body = json.loads(response.read().decode())
        calendar = (
            body["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        )
        return int(calendar["totalContributions"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        # Every failure mode lands here on purpose: an outage, a rate limit, a renamed
        # account and a changed response shape are all "no number today", and none of
        # them may propagate into a profile read.
        logger.warning("github_contributions_failed", extra={"login": login, "error": str(exc)})
        return None
