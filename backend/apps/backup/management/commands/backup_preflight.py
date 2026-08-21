"""Host-side build and setting checks used by backup restore preflight."""

import hashlib
import json
import os
from pathlib import Path
import sys

from django.core.management.base import CommandError

from apps.backup.settings_policy import POLICIES, Policy


def build_info():
    path = Path("/app/BUILD_INFO.json")
    if not path.exists():
        return {"source_hash": "unknown"}
    return json.loads(path.read_text(encoding="utf-8"))


def check_setting_policies(archived):
    blocking = []
    warnings = []
    for name, policy in POLICIES.items():
        if policy.policy == Policy.EXCLUDED:
            continue
        fact = archived.get(name, {})
        raw = os.environ.get(name, "")
        if policy.policy == Policy.EXACT_FINGERPRINT:
            matches = fact.get("fingerprint") == hashlib.sha256(
                raw.encode()
            ).hexdigest()
        elif policy.policy == Policy.CAPABILITY_PROBE:
            matches = not fact.get("configured") or bool(raw)
        else:
            matches = fact.get("value", "") == raw
        if not matches:
            (blocking if policy.blocks_restore else warnings).append(name)
    if blocking:
        raise CommandError(
            f"Restore-blocking setting preflight failed: {', '.join(sorted(blocking))}."
        )
    if warnings:
        print(
            f"WARNING: non-blocking settings differ: {', '.join(sorted(warnings))}.",
            file=sys.stderr,
        )
