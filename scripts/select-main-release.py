#!/usr/bin/env python3
"""Choose the newest published immutable main release without Django or a database."""
import json
import re
import sys

TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}")
MAX_RESPONSE_SIZE = 2_000_000


def published_main(release):
    return (isinstance(release, dict)
            and release.get("draft") is False and release.get("prerelease") is False
            and isinstance(release.get("published_at"), str) and bool(release["published_at"])
            and isinstance(release.get("tag_name"), str)
            and TAG_PATTERN.fullmatch(release["tag_name"]))


def select_release(raw, version="", repository=""):
    if len(raw) > MAX_RESPONSE_SIZE:
        raise ValueError("The GitHub release response exceeds its size limit.")
    releases = json.loads(raw)
    if version:
        if not TAG_PATTERN.fullmatch(f"v{version}"):
            raise ValueError("Invalid pinned main release version.")
        if not published_main(releases) or releases["tag_name"] != f"v{version}":
            raise ValueError("The pinned tag is not a published, non-prerelease main release.")
        # The API can redirect renamed repositories. Check the returned repository too.
        expected = f"https://github.com/{repository}/releases/tag/v{version}"
        if str(releases.get("html_url", "")).lower() != expected.lower():
            raise ValueError("The pinned release belongs to a different repository.")
        return version
    if not isinstance(releases, list):
        raise ValueError("GitHub did not return a release list.")
    candidates = [r for r in releases[:100] if published_main(r)]
    if not candidates:
        raise ValueError("No published, non-prerelease main release is available.")
    # GitHub lists creation order; publication order determines the newest release.
    newest = max(candidates, key=lambda r: (str(r.get("published_at", "")), r["tag_name"]))
    return newest["tag_name"][1:]


def main():
    try:
        print(select_release(sys.stdin.read(MAX_RESPONSE_SIZE + 1), *sys.argv[1:3]))
    except (ValueError, RecursionError) as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
