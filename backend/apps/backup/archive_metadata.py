"""Stable build and settings metadata used by backup archive manifests."""

import hashlib
import json
import os
from pathlib import Path

from apps.backup.settings_policy import POLICIES, Policy


def build_info():
    path = Path("/app/BUILD_INFO.json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "git_sha": "unknown",
        "git_describe": "unknown",
        "built_at": "unknown",
        "source_hash": "unknown",
    }


def settings_manifest():
    result = {}
    for name, entry in POLICIES.items():
        if entry.policy == Policy.EXCLUDED:
            continue
        raw = os.environ.get(name, "")
        if entry.policy == Policy.EXACT_FINGERPRINT:
            fact = {"fingerprint": hashlib.sha256(raw.encode()).hexdigest()}
        elif entry.policy == Policy.CAPABILITY_PROBE:
            # Infrastructure credentials never enter the database-backed manifest.
            fact = {"configured": bool(raw)}
        else:
            fact = {"value": raw}
        result[name] = {
            "policy": entry.policy,
            "blocks_restore": entry.blocks_restore,
            **fact,
        }
    return result


# Preserve the private names used by the original K2 split and existing callers.
_build_info = build_info
_settings_manifest = settings_manifest
