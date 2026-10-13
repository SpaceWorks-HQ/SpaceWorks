#!/usr/bin/env python3
"""Choose the newest published immutable main release without Django or a database."""
import json
import re
import sys

TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}")
MAX_RESPONSE_SIZE = 2_000_000


def select_release(raw):
    if len(raw) > MAX_RESPONSE_SIZE:
        raise ValueError("The GitHub release response exceeds its size limit.")
    releases = json.loads(raw)
    if not isinstance(releases, list):
        raise ValueError("GitHub did not return a release list.")
    candidates = [r for r in releases[:100] if isinstance(r, dict)
                  and r.get("draft") is False and r.get("prerelease") is False
                  and isinstance(r.get("tag_name"), str)
                  and TAG_PATTERN.fullmatch(r["tag_name"])]
    if not candidates:
        raise ValueError("No published, non-prerelease main release is available.")
    # GitHub lists creation order; publication order determines the newest release.
    newest = max(candidates, key=lambda r: (str(r.get("published_at", "")), r["tag_name"]))
    return newest["tag_name"][1:]


def main():
    try:
        print(select_release(sys.stdin.read(MAX_RESPONSE_SIZE + 1)))
    except (ValueError, RecursionError) as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
