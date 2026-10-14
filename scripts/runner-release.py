#!/usr/bin/env python3
"""Select the Linux runner asset and its published SHA-256, failing closed."""
import json
import re
import sys


def select(document, architecture):
    if not isinstance(document, dict):
        raise ValueError("Invalid runner release metadata.")
    tag = document.get("tag_name", "")
    if (not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)
            or document.get("draft") is not False
            or document.get("prerelease") is not False
            or not document.get("published_at")):
        raise ValueError("The latest runner release is not a published stable release.")
    name = f"actions-runner-linux-{architecture}-{tag[1:]}.tar.gz"
    expected_url = f"https://github.com/actions/runner/releases/download/{tag}/{name}"
    entries = document.get("assets")
    if not isinstance(entries, list) or any(not isinstance(asset, dict) for asset in entries):
        raise ValueError("Invalid runner asset metadata.")
    assets = [asset for asset in entries if asset.get("name") == name]
    if len(assets) != 1 or assets[0].get("browser_download_url") != expected_url:
        raise ValueError("The runner release has no matching official Linux asset.")
    checksums = set()
    digest = assets[0].get("digest") or ""
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        checksums.add(digest.split(":", 1)[1].lower())
    body = document.get("body") or ""
    if not isinstance(body, str):
        raise ValueError("Invalid runner release notes.")
    for line in body.splitlines():
        # Release notes publish a filename/hash table. Require the exact filename.
        if re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])", line):
            checksums.update(value.lower() for value in re.findall(
                r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])", line))
    if len(checksums) != 1:
        raise ValueError("No unambiguous published SHA-256 exists for the runner asset.")
    return expected_url, checksums.pop()


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"x64", "arm64"}:
            raise ValueError("Expected x64 or arm64 architecture.")
        print("\n".join(select(json.load(sys.stdin), sys.argv[1])))
    except (ValueError, TypeError, KeyError) as exc:
        sys.exit(f"ERROR: {exc}")
