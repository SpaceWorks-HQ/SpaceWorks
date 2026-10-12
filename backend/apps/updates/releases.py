"""Select completed GitHub releases without trusting display titles or HTML."""

import re
from datetime import datetime

VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+-(main|beta)\.[0-9]+\.[0-9a-f]{12}")


def release_allowed(version, channel, *, prerelease=False):
    match = VERSION_PATTERN.fullmatch(version)
    return bool(match and (channel == "beta" or (match[1] == "main" and not prerelease)))


def select_release(releases, channel):
    if not isinstance(releases, list) or channel not in {"stable", "beta"}:
        raise ValueError("Expected a GitHub release list and a stable/beta channel.")
    candidates = []
    for release in releases[:100]:
        if not isinstance(release, dict) or release.get("draft") is not False:
            continue
        tag = release.get("tag_name")
        prerelease = release.get("prerelease")
        if not isinstance(tag, str) or not tag.startswith("v") or type(prerelease) is not bool:
            continue
        if not release_allowed(tag[1:], channel, prerelease=prerelease):
            continue
        try:
            published = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                continue
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        url = release.get("html_url", "")
        if not isinstance(url, str) or not url.startswith(
            "https://github.com/SpaceWorks-HQ/SpaceWorks/releases/tag/"
        ):
            url = ""
        notes = release.get("body")
        candidates.append((published, {
            "version": tag[1:],
            "notes": notes[:100_000] if isinstance(notes, str) else "",
            "url": url[:200],
        }))
    if not candidates:
        raise ValueError(f"No completed release is available on the {channel} channel.")
    return max(candidates, key=lambda row: row[0])[1]
