#!/usr/bin/env python3
"""Constrain old installed backends to published main releases before claiming."""

import json
import re
import sys


TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}")
MAX_RESPONSE_SIZE = 2_000_000


def filter_releases(raw):
    if len(raw) > MAX_RESPONSE_SIZE:
        raise ValueError("The GitHub release response exceeds its size limit.")
    try:
        releases = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("GitHub returned malformed release JSON.") from exc
    if not isinstance(releases, list):
        raise ValueError("GitHub did not return a release list.")
    candidates = [
        release for release in releases[:100]
        if isinstance(release, dict)
        and release.get("draft") is False
        and release.get("prerelease") is False
        and isinstance(release.get("tag_name"), str)
        and TAG_PATTERN.fullmatch(release["tag_name"])
    ]
    if not candidates:
        raise ValueError("No published, non-prerelease main release is available.")
    return candidates


def main():
    try:
        releases = filter_releases(sys.stdin.read(MAX_RESPONSE_SIZE + 1))
    except ValueError as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        return 1
    # Keep publication dates and release notes for the backend's existing claim
    # logic. Even a backend with a persisted beta preference now only sees main.
    json.dump(releases, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
