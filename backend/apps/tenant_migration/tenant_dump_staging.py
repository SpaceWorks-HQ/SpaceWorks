"""Run-owned secure staging with conservative crash cleanup."""

import json
import logging
from pathlib import Path
import shutil
import time

from django.conf import settings


logger = logging.getLogger(__name__)
MARKER = ".spaceworks-tenant-dump-owner.json"
MARKER_KIND = "spaceworks-tenant-dump-capture-v1"


def staging_base():
    configured = getattr(settings, "TENANT_DUMP_STAGING_DIR", "")
    return Path(configured or Path(settings.BACKUP_OPS_DIR, "tenant-dump-captures"))


def capture_root(capture_id):
    return staging_base() / str(capture_id)


def create_capture_root(capture_id):
    base = staging_base()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    base.chmod(0o700)
    root = capture_root(capture_id)
    root.mkdir(mode=0o700, exist_ok=False)
    root.chmod(0o700)
    marker = root / MARKER
    marker.write_text(
        json.dumps(
            {"kind": MARKER_KIND, "capture_id": str(capture_id), "created_at": time.time()},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    marker.chmod(0o600)
    return root


def require_owned_root(capture_id):
    root = capture_root(capture_id)
    try:
        payload = json.loads((root / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Lane D staging is missing its ownership marker.") from exc
    if payload.get("kind") != MARKER_KIND or payload.get("capture_id") != str(capture_id):
        raise RuntimeError("Lane D staging ownership does not match the capture.")
    return root


def delete_owned_root(capture_id):
    root = require_owned_root(capture_id)
    shutil.rmtree(root)


def sweep_stale_staging(*, now=None):
    base = staging_base()
    if not base.is_dir():
        return 0
    cutoff = (now or time.time()) - int(
        getattr(settings, "TENANT_DUMP_STAGING_MAX_AGE_SECONDS", 7 * 24 * 60 * 60)
    )
    removed = 0
    for root in base.iterdir():
        if not root.is_dir():
            continue
        try:
            payload = json.loads((root / MARKER).read_text(encoding="utf-8"))
            owned = payload.get("kind") == MARKER_KIND
            stale = float(payload.get("created_at", 0)) < cutoff
            if owned and stale:
                shutil.rmtree(root)
                removed += 1
        except (OSError, TypeError, ValueError):
            logger.warning("tenant_dump_staging_unowned_or_invalid", extra={"path": str(root)})
    return removed
